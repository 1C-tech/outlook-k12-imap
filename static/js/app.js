const { createApp } = Vue;

createApp({
  data() {
    return {
      token: localStorage.getItem("k12_token") || "",
      password: "",
      loading: false,
      error: "",
      currentTab: "dashboard",
      mobileNavOpen: false,
      isDark: localStorage.getItem("ui_theme_mode") === "dark",
      tabs: [
        { id: "dashboard", label: "控制台日志", icon: "▦" },
        { id: "accounts", label: "微软邮箱", icon: "@" },
        { id: "settings", label: "设置", icon: "⚙" },
      ],
      importText: "",
      importResult: null,
      accountSearch: "",
      accountStatusFilter: "",
      selectedAccountIds: [],
      accounts: [],
      accountPage: {},
      tasks: [],
      taskPage: {},
      logs: [],
      logPage: {},
      selectedLog: null,
      logFilters: { email: "", level: "", task_id: "" },
      settings: { k12: {}, registration: {} },
      notice: "",
      logStream: null,
      logStreamConnected: false,
    };
  },
  mounted() {
    this.applyTheme();
    if (this.token) {
      this.loadAll()
        .then(() => this.startLogStream())
        .catch((err) => { this.notice = err.message; });
    }
  },
  beforeUnmount() {
    this.stopLogStream();
  },
  computed: {
    allAccountsSelected() {
      return this.accounts.length > 0 && this.accounts.every((account) => this.selectedAccountIds.includes(account.id));
    },
    accountStatusOptions() {
      return [
        { value: 0, label: "未注册" },
        { value: 1, label: "注册完成未邀请" },
        { value: 2, label: "注册完成并邀请成功" },
      ];
    },
  },
  methods: {
    headers() {
      return { "Content-Type": "application/json", Authorization: `Bearer ${this.token}` };
    },
    async api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: { ...this.headers(), ...(options.headers || {}) },
      });
      if (response.status === 401) {
        this.token = "";
        localStorage.removeItem("k12_token");
        throw new Error("登录已过期，请重新登录");
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || "请求失败");
      return data;
    },
    async login() {
      this.loading = true;
      this.error = "";
      try {
        const data = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: this.password }),
        }).then(async (r) => {
          const data = await r.json();
          if (!r.ok) throw new Error(data.detail || "登录失败");
          return data;
        });
        this.token = data.token;
        localStorage.setItem("k12_token", this.token);
        await this.loadAll();
        this.startLogStream();
      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
    async logout() {
      try { await this.api("/api/auth/logout", { method: "POST" }); } catch (_) {}
      this.stopLogStream();
      this.token = "";
      localStorage.removeItem("k12_token");
    },
    switchTab(tab) {
      this.currentTab = tab;
      this.mobileNavOpen = false;
      this.notice = "";
      const loaders = {
        accounts: () => this.loadAccounts(),
        dashboard: () => this.loadLogs(),
        settings: () => this.loadSettings(),
      };
      if (loaders[tab]) {
        loaders[tab]().catch((err) => {
          this.notice = err.message || "加载失败";
        });
      }
    },
    applyTheme() {
      document.body.classList.toggle("theme-dark", this.isDark);
      localStorage.setItem("ui_theme_mode", this.isDark ? "dark" : "light");
    },
    toggleTheme() {
      this.isDark = !this.isDark;
      this.applyTheme();
    },
    async loadAll() {
      await Promise.all([this.loadAccounts(), this.loadTasks(), this.loadLogs(), this.loadSettings()]);
    },
    async loadAccounts() {
      const q = new URLSearchParams({ page: 1, page_size: 50, search: this.accountSearch || "" });
      if (this.accountStatusFilter !== "") q.set("status", this.accountStatusFilter);
      const data = await this.api(`/api/accounts?${q}`);
      this.accounts = data.data;
      this.accountPage = data;
      const visibleIds = new Set(this.accounts.map((account) => account.id));
      this.selectedAccountIds = this.selectedAccountIds.filter((id) => visibleIds.has(id));
    },
    async importAccounts() {
      this.importResult = await this.api("/api/accounts/import", {
        method: "POST",
        body: JSON.stringify({ raw_text: this.importText }),
      });
      this.notice = `导入完成：新增 ${this.importResult.count} 条，覆盖 ${this.importResult.updated || 0} 条，失败 ${this.importResult.failed} 条`;
      await this.loadAccounts();
    },
    async deleteAccount(id) {
      await this.api("/api/accounts", { method: "DELETE", body: JSON.stringify({ ids: [id] }) });
      this.notice = "账号已删除";
      await this.loadAccounts();
    },
    async deleteSelectedAccounts() {
      if (!this.selectedAccountIds.length) return;
      const data = await this.api("/api/accounts", { method: "DELETE", body: JSON.stringify({ ids: this.selectedAccountIds }) });
      this.notice = `已删除 ${data.deleted} 个账号`;
      this.selectedAccountIds = [];
      await this.loadAccounts();
    },
    async createAndRun(id) {
      const created = await this.api("/api/tasks", { method: "POST", body: JSON.stringify({ account_ids: [id] }) });
      if (created.task_ids[0]) await this.startTask(created.task_ids[0]);
      this.currentTab = "dashboard";
      await this.loadAll();
    },
    toggleAllAccounts(event) {
      this.selectedAccountIds = event.target.checked ? this.accounts.map((account) => account.id) : [];
    },
    async createAndRunSelected() {
      if (!this.selectedAccountIds.length) return;
      const created = await this.api("/api/tasks", {
        method: "POST",
        body: JSON.stringify({ account_ids: this.selectedAccountIds }),
      });
      await Promise.all((created.task_ids || []).map((id) => this.startTask(id)));
      this.selectedAccountIds = [];
      this.currentTab = "dashboard";
      await this.loadAll();
    },
    async runUnfinishedAccounts() {
      const result = await this.api("/api/tasks/run_unfinished", { method: "POST" });
      this.notice = `${result.message || "已启动"}：未注册 ${result.registration_count || 0} 个，待邀请 ${result.invite_count || 0} 个，并发 ${result.concurrency || 1}`;
      await this.loadLogs();
      this.startLogStream();
    },
    startLogStream() {
      if (!this.token || this.logStream) return;
      const url = `/api/logs/stream?token=${encodeURIComponent(this.token)}&_t=${Date.now()}`;
      this.logStream = new EventSource(url);
      this.logStreamConnected = true;
      this.logStream.onmessage = (event) => {
        try {
          const log = JSON.parse(event.data);
          this.appendLog(log);
        } catch (_) {}
      };
      this.logStream.onerror = () => {
        this.stopLogStream();
        if (this.token) setTimeout(() => this.startLogStream(), 3000);
      };
    },
    stopLogStream() {
      if (this.logStream) {
        this.logStream.close();
        this.logStream = null;
      }
      this.logStreamConnected = false;
    },
    logMatchesFilters(log) {
      if (this.logFilters.level && String(log.level || "").toUpperCase() !== this.logFilters.level) return false;
      if (this.logFilters.task_id && String(log.task_id || "") !== String(this.logFilters.task_id)) return false;
      if (this.logFilters.email && !String(log.email || "").includes(this.logFilters.email)) return false;
      return true;
    },
    appendLog(log) {
      if (!log || !log.id || this.logs.some((item) => item.id === log.id) || !this.logMatchesFilters(log)) return;
      const list = this.$refs.logList;
      const shouldStickToBottom = !list || (list.scrollHeight - list.clientHeight - list.scrollTop < 80);
      this.logs.push(log);
      if (this.logs.length > 200) this.logs.splice(0, this.logs.length - 200);
      this.logPage.total = (this.logPage.total || 0) + 1;
      this.$nextTick(() => {
        if (shouldStickToBottom) this.scrollLogsToBottom();
      });
    },
    scrollLogsToBottom() {
      const list = this.$refs.logList;
      if (list) list.scrollTop = list.scrollHeight;
    },
    async loadTasks() {
      const data = await this.api("/api/tasks?page=1&page_size=50");
      this.tasks = data.data;
      this.taskPage = data;
    },
    async startTask(id) {
      await this.api(`/api/tasks/${id}/start`, { method: "POST" });
      this.notice = `任务 ${id} 已启动`;
      setTimeout(() => this.loadAll().catch((err) => { this.notice = err.message; }), 800);
    },
    async clearLogs() {
      const data = await this.api("/api/logs/clear", { method: "POST" });
      this.selectedLog = null;
      this.logs = [];
      this.logPage = { total: 0 };
      this.stopLogStream();
      await this.loadLogs();
      if ((this.logPage.total || 0) > 0) {
        this.notice = `已请求清空 ${data.deleted} 条日志，但仍检测到 ${this.logPage.total} 条，请重启后端服务后再试`;
        return;
      }
      this.notice = `已清空 ${data.deleted} 条日志`;
      this.startLogStream();
    },
    async loadLogs() {
      const q = new URLSearchParams({ page: 1, page_size: 80 });
      Object.entries(this.logFilters).forEach(([key, value]) => {
        if (value) q.set(key, value);
      });
      const data = await this.api(`/api/logs?${q}`);
      this.logs = (data.data || []).slice().reverse();
      this.logPage = data;
      this.$nextTick(() => this.scrollLogsToBottom());
    },
    async loadSettings() {
      this.settings = await this.api("/api/settings");
    },
    async saveSettings() {
      await this.api("/api/settings", { method: "PUT", body: JSON.stringify(this.settings) });
      await this.api("/api/settings/reload", { method: "POST" });
      this.notice = "配置已保存";
      await this.loadSettings();
    },
  },
}).mount("#app");
