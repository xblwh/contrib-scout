export {};

type Source = { id: string; label: string; url: string; excerpt: string };
type Candidate = {
  number: number;
  title: string;
  url: string;
  status: string;
  status_label: string;
  created_at: string | null;
  updated_at: string | null;
  labels: string[];
  assignees: string[];
  reasons: string[];
  risks: string[];
  sources: Source[];
  next_steps: string[];
  related_prs: {
    number: number;
    title: string;
    url: string;
    state: string;
    reason: string;
  }[];
  ai: null | {
    summary: string;
    suggested_scope: string;
    verification_plan: string;
    source_ids: string[];
  };
};
type PolicyFinding = {
  id: string;
  path: string;
  line: number;
  url: string;
  quote: string;
  categories: string[];
  inherited: boolean;
  quote_truncated?: boolean;
};
type Report = {
  demo: boolean;
  generated_at: string;
  stack: string[];
  target?: { mode: string; input: string; issue_number: number | null };
  policy?: {
    note: string;
    contributing_found: boolean;
    findings: PolicyFinding[];
  };
  repository: {
    name: string;
    url: string;
    description: string;
    language: string | null;
    license: string;
    stars: number;
    archived: boolean;
    pushed_at: string | null;
    default_branch: string;
  };
  candidates: Candidate[];
  documents: { id: string; path: string; url: string; text: string }[];
  warnings: string[];
  coverage: {
    issues_scanned: number;
    open_prs_scanned: number;
    open_prs_complete: boolean;
    closed_prs_scanned?: number;
    closed_prs_complete?: boolean;
    note: string;
  };
  metrics: { github_requests: number; elapsed_seconds: number };
  ai: {
    enabled: boolean;
    error?: string;
    model?: string;
    elapsed_seconds?: number;
    usage?: { total_tokens: number | null };
    estimated_cost_usd?: number | null;
  };
};
type Result = { report: Report; markdown: string };
type Job = Partial<Result> & {
  state: string;
  error?: string;
  progress?: string;
};

const $ = <T extends HTMLElement = HTMLElement>(id: string): T => {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing element: ${id}`);
  return value as T;
};
const el = (tag: string, className = "", text = ""): HTMLElement => {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
};
let current: Result | null = null;
let filter = "all";
let csrf = "";
let busy = false;
let downloadUrl = "/api/demo.md";
const storageKey = "contrib-scout:last-report";
function remember(value: string | null): void {
  try {
    if (value) sessionStorage.setItem(storageKey, value);
    else sessionStorage.removeItem(storageKey);
  } catch {
    /* Storage may be disabled. */
  }
}
function remembered(): string | null {
  try {
    return sessionStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

function link(text: string, url: string): HTMLElement {
  const node = el("a", "source-link", text) as HTMLAnchorElement;
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol === "https:" &&
      parsed.hostname === "github.com" &&
      !current?.report.demo
    ) {
      node.href = parsed.href;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    } else {
      node.removeAttribute("href");
      node.title = "演示来源，无实际链接";
    }
  } catch {
    node.title = "来源地址无效";
  }
  return node;
}
function date(value: string | null): string {
  return value ? value.slice(0, 10) : "未知";
}
function list(items: string[], className = ""): HTMLElement {
  const node = el("ul", className);
  items.forEach((item) => node.append(el("li", "", item)));
  return node;
}
function feedback(message: string, state = "info"): void {
  const node = $("feedback");
  node.hidden = !message;
  node.className = `feedback ${state}`;
  node.textContent = message;
}
function busyUI(value: boolean): void {
  busy = value;
  $<HTMLButtonElement>("submit").disabled = value;
  $<HTMLButtonElement>("demo").disabled = value;
  $<HTMLButtonElement>("empty-demo").disabled = value;
  $("submit").textContent = value ? "正在读取来源…" : "开始调研 ↗";
  document.querySelector(".results")?.setAttribute("aria-busy", String(value));
}
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = (await response.json()) as T & { error?: string };
  if (!response.ok)
    throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function renderCandidates(): void {
  if (!current) return;
  const container = $("candidates");
  container.replaceChildren();
  const items = current.report.candidates.filter(
    (item) =>
      filter === "all" ||
      (filter === "attention"
        ? item.status !== "investigate"
        : item.status === filter),
  );
  if (!items.length) {
    container.append(
      el(
        "p",
        "no-results",
        "这个范围内没有候选。可以调整筛选，或换一个仓库继续调研。",
      ),
    );
    return;
  }
  items.forEach((item, index) => {
    const card = el("article", `candidate ${item.status}`);
    const top = el("div", "card-top");
    top.append(
      el("span", "issue-number", `ISSUE #${item.number}`),
      el("span", `badge ${item.status}`, item.status_label),
    );
    const heading = el("h4");
    heading.append(link(item.title, item.url));
    const meta = el(
      "div",
      "card-meta",
      `创建 ${date(item.created_at)} · 更新 ${date(item.updated_at)}`,
    );
    const tags = el("div", "labels");
    item.labels
      .slice(0, 5)
      .forEach((label) => tags.append(el("span", "", label)));
    const reason = el("p", "match-reason", item.reasons.join(" · "));
    card.append(top, heading, meta, tags, reason);
    if (item.risks.length) {
      const risks = el("div", "risk-box");
      risks.append(el("strong", "", "需要留意"), list(item.risks));
      card.append(risks);
    } else {
      card.append(
        el(
          "p",
          "quiet-note",
          "当前扫描范围内未发现认领或关联 PR 风险；贡献规则与源码仍待核实。",
        ),
      );
    }
    const details = el("details", "candidate-details") as HTMLDetailsElement;
    details.open = index === 0;
    details.append(el("summary", "", "查看证据与下一步"));
    const content = el("div", "detail-content");
    content.append(
      el("div", "mini-label", "建议下一步"),
      list(item.next_steps, "next-steps"),
    );
    if (item.ai) {
      const analysis = el("div", "ai-analysis");
      analysis.append(
        el("div", "mini-label", "AI 建议 · 未执行"),
        el("p", "", item.ai.summary),
        el("p", "", item.ai.suggested_scope),
        el("p", "", item.ai.verification_plan),
      );
      const refs = el("div", "ai-refs");
      const lookup = new Map([
        ...item.sources.map(
          (source) =>
            [source.id, { url: source.url, label: source.label }] as const,
        ),
        ...(current!.report.policy?.findings ?? []).map(
          (finding) =>
            [
              finding.id,
              { url: finding.url, label: `${finding.path}:${finding.line}` },
            ] as const,
        ),
        ...current!.report.documents.map(
          (doc) => [doc.id, { url: doc.url, label: doc.path }] as const,
        ),
      ]);
      item.ai.source_ids.forEach((id) => {
        const source = lookup.get(id);
        if (source) refs.append(link(source.label, source.url));
      });
      analysis.append(refs);
      content.append(analysis);
    }
    content.append(el("div", "mini-label", "来源证据"));
    item.sources.forEach((source) => {
      const block = el("div", "evidence");
      block.append(
        link(source.label + " ↗", source.url),
        el("blockquote", "", source.excerpt.slice(0, 700)),
      );
      content.append(block);
    });
    details.append(content);
    card.append(details);
    container.append(card);
  });
}

function render(result: Result): void {
  current = result;
  filter = "all";
  document
    .querySelectorAll<HTMLButtonElement>("[data-filter]")
    .forEach((button) => {
      const active = button.dataset.filter === "all";
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  const report = result.report,
    repo = report.repository;
  $("target-note").textContent = report.target?.issue_number
    ? `定向调研 · Issue #${report.target.issue_number}`
    : "仓库候选调研";
  $("empty").hidden = true;
  $("report").hidden = false;
  $("demo-banner").hidden = !report.demo;
  $("report-mode").textContent = report.demo
    ? "DEMO / FICTIONAL DATA"
    : "RESEARCH REPORT / LIVE DATA";
  $("repo-name").replaceChildren(link(repo.name + " ↗", repo.url));
  $("repo-meta").textContent =
    `${repo.language || "语言未识别"} · ${repo.license} · ${repo.stars.toLocaleString()} stars · 最近推送 ${date(repo.pushed_at)}${repo.archived ? " · 已归档" : ""}`;
  const stats = $("stats");
  stats.replaceChildren();
  [
    [String(report.coverage.issues_scanned), "扫描的问题"],
    [String(report.coverage.open_prs_scanned), "检查的开放 PR"],
    [String(report.coverage.closed_prs_scanned ?? 0), "检查的关闭 PR"],
    [
      String(
        report.candidates.filter((item) => item.status === "investigate")
          .length,
      ),
      "可继续调研",
    ],
  ].forEach(([value, label]) => {
    const stat = el("div", "stat");
    stat.append(el("strong", "", value), el("span", "", label));
    stats.append(stat);
  });
  const documents = $("documents");
  documents.replaceChildren(el("span", "mini-label", "仓库文档"));
  report.documents.forEach((doc) =>
    documents.append(
      link(
        doc.path +
          ((doc as { inherited?: boolean }).inherited ? "（共享）" : "") +
          " ↗",
        doc.url,
      ),
    ),
  );
  if (!report.documents.length)
    documents.append(el("span", "", "未读取到文档，请人工核实"));
  renderPolicy(report);
  $("warning-count").textContent = report.warnings.length
    ? `${report.warnings.length} 条提示`
    : "范围说明";
  $("coverage-body").replaceChildren(
    el("p", "", report.coverage.note),
    list(report.warnings),
  );
  $("candidate-count").textContent = String(report.candidates.length);
  let footer = `采集于 ${date(report.generated_at)} · ${report.metrics.github_requests} 次 GitHub 请求 · ${report.metrics.elapsed_seconds}s`;
  if (report.ai.enabled)
    footer += ` · AI ${report.ai.model} · ${report.ai.usage?.total_tokens ?? "未知"} tokens · 估算费用 ${report.ai.estimated_cost_usd == null ? "未知（价格或用量不完整）" : `$${report.ai.estimated_cost_usd}`}`;
  else footer += " · 基础调研模式";
  $("report-footer").textContent = footer;
  renderCandidates();
  if (report.ai.error)
    feedback(`GitHub 调研已完成；AI 分析未完成：${report.ai.error}`, "error");
}

function renderPolicy(report: Report): void {
  const container = $("policy");
  container.replaceChildren();
  const details = el("details", "policy-details") as HTMLDetailsElement;
  const findings = report.policy?.findings ?? [];
  details.append(
    el("summary", "", `贡献规则原文线索 · ${findings.length} 条待核实`),
  );
  details.append(
    el(
      "p",
      "policy-note",
      report.policy?.note ??
        "演示仅展示规则入口；真实报告会提取带行号的原文线索。",
    ),
  );
  if (!findings.length)
    details.append(
      el("p", "quiet-note", "未命中关键词不代表没有贡献限制，请阅读完整文档。"),
    );
  for (const finding of findings) {
    const block = el("div", "policy-finding");
    block.append(
      el(
        "span",
        "mini-label",
        finding.categories.join(" / ") +
          (finding.inherited ? " · 共享规则，适用范围待确认" : ""),
      ),
      link(`${finding.path}:${finding.line} ↗`, finding.url),
      el(
        "blockquote",
        "",
        finding.quote + (finding.quote_truncated ? "…（摘录截断）" : ""),
      ),
    );
    details.append(block);
  }
  container.append(details);
}

async function waitForJob(jobId: string, started = Date.now()): Promise<void> {
  let failures = 0;
  while (Date.now() - started < 900_000) {
    let result: Job;
    try {
      result = await api<Job>(`/api/jobs/${jobId}`);
      failures = 0;
    } catch (error) {
      failures++;
      if (failures >= 3) throw error;
      feedback("连接暂时中断，正在重试读取任务状态…", "loading");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      continue;
    }
    if (result.state === "error") {
      remember(null);
      throw new Error(result.error || "调研失败。");
    }
    if (result.state === "complete" && result.report && result.markdown) {
      feedback("");
      downloadUrl = `/api/jobs/${jobId}/report.md`;
      $("repo").setAttribute(
        "value",
        result.report.target?.input ?? result.report.repository.name,
      );
      $<HTMLInputElement>("repo").value =
        result.report.target?.input ?? result.report.repository.name;
      $<HTMLInputElement>("stack").value = result.report.stack.join(", ");
      render({ report: result.report, markdown: result.markdown });
      return;
    }
    feedback(
      `${result.progress || "正在核对来源"} · 本次等待 ${Math.floor((Date.now() - started) / 1000)} 秒`,
      "loading",
    );
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new Error("等待超时。任务可能仍在运行，可以稍后刷新本页恢复。");
}

async function loadDemo(): Promise<void> {
  if (busy) return;
  try {
    busyUI(true);
    feedback("");
    const result = await api<Result>("/api/demo");
    downloadUrl = "/api/demo.md";
    remember("demo");
    render(result);
  } catch (error) {
    feedback(
      error instanceof Error ? error.message : "演示加载失败。",
      "error",
    );
  } finally {
    busyUI(false);
  }
}
$("demo").addEventListener("click", loadDemo);
$("empty-demo").addEventListener("click", loadDemo);
$("research-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  busyUI(true);
  feedback("正在读取仓库与问题。刷新本页也可以恢复当前任务。", "loading");
  const started = Date.now();
  try {
    if (!csrf) csrf = (await api<{ csrf: string }>("/api/config")).csrf;
    const job = await api<{ job_id: string }>("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Scout-Token": csrf },
      body: JSON.stringify({
        repo: $<HTMLInputElement>("repo").value,
        stack: $<HTMLInputElement>("stack").value,
        limit: Number($<HTMLSelectElement>("limit").value),
        ai: $<HTMLInputElement>("ai").checked,
      }),
    });
    remember(job.job_id);
    await waitForJob(job.job_id, started);
  } catch (error) {
    feedback(
      error instanceof Error
        ? error.message
        : "网络请求失败，请确认本地服务仍在运行。",
      "error",
    );
  } finally {
    busyUI(false);
  }
});
document
  .querySelectorAll<HTMLButtonElement>("[data-filter]")
  .forEach((button) =>
    button.addEventListener("click", () => {
      filter = button.dataset.filter || "all";
      document
        .querySelectorAll<HTMLButtonElement>("[data-filter]")
        .forEach((other) => {
          const active = other === button;
          other.classList.toggle("active", active);
          other.setAttribute("aria-pressed", String(active));
        });
      renderCandidates();
    }),
  );
$("export").addEventListener("click", () => {
  if (!current) return;
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  anchor.download = "research.md";
  anchor.click();
});
$("export-json").addEventListener("click", () => {
  if (!current) return;
  const anchor = document.createElement("a");
  anchor.href = downloadUrl.replace(/\.md$/, ".json");
  anchor.download = "research.json";
  anchor.click();
});
api<{ ai_configured: boolean; csrf: string }>("/api/config")
  .then(async (config) => {
    csrf = config.csrf;
    $<HTMLInputElement>("ai").disabled = !config.ai_configured;
    $("ai-note").textContent = config.ai_configured
      ? "模型已配置，按需启用"
      : "未配置模型 · 基础调研可用";
    const last = remembered();
    if (!last || busy) return;
    if (last === "demo") {
      await loadDemo();
      return;
    }
    if (!/^[a-zA-Z0-9_-]{10,64}$/.test(last)) {
      remember(null);
      return;
    }
    busyUI(true);
    feedback("正在恢复上次调研…", "loading");
    try {
      await waitForJob(last);
    } catch (error) {
      remember(null);
      feedback(
        `未能恢复上次报告：${error instanceof Error ? error.message : "服务可能已重启"}。可以重新开始调研。`,
        "error",
      );
    } finally {
      busyUI(false);
    }
  })
  .catch(() => {
    $("ai-note").textContent = "未连接本地服务";
    feedback("无法连接服务，请刷新页面重试。", "error");
  });
