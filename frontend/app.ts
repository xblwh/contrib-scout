export {};

type Source = {
  id: string;
  label: string;
  url: string;
  excerpt: string;
  category?: string;
};
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
  relevance?: {
    kind: string;
    label: string;
    note: string;
    evidence: {
      label: string;
      excerpt: string;
      terms: string[];
      source_id?: string;
      url: string;
    }[];
  };
  policy_check?: {
    status: string;
    documents_complete: boolean;
    contributing_found: boolean;
    finding_count: number;
  };
  action_plan?: {
    kind: string;
    title: string;
    detail: string;
    source_ids: string[];
  }[];
  source_hints?: {
    files: {
      path: string;
      url: string;
      excerpt: string;
      note: string;
      source_id?: string;
    }[];
    unverified: { path: string; reason: string }[];
    paths_omitted?: number;
    note: string;
    snapshot: string | null;
  };
  problem_evidence?: { label: string; text: string; truncated: boolean }[];
  reproduction?: {
    language: string;
    text: string;
    truncated: boolean;
    note: string;
  } | null;
  related_prs: {
    number: number;
    title: string;
    url: string;
    state: string;
    reason: string;
    repository?: string;
    relation?: string;
    relation_label?: string;
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
  selection?: {
    include_unmatched: boolean;
    unmatched_excluded: number;
    matched_available: number;
    requested: number;
  };
  policy?: {
    note: string;
    contributing_found: boolean;
    documents_complete?: boolean;
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
    source_lookup_enabled?: boolean;
    source_paths_checked?: number;
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
type ResearchRequest = {
  repo: string;
  stack: string;
  limit: number;
  ai: boolean;
  include_unmatched: boolean;
  check_sources: boolean;
};
type Job = Partial<Result> & {
  state: string;
  error?: string;
  progress?: string;
  request?: ResearchRequest;
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
let aiConfigured = false;
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
  for (const id of [
    "repo",
    "stack",
    "limit",
    "include-unmatched",
    "check-sources",
  ]) {
    $<HTMLInputElement | HTMLSelectElement>(id).disabled = value;
  }
  $<HTMLInputElement>("ai").disabled = value || !aiConfigured;
  $<HTMLButtonElement>("submit").disabled = value;
  $<HTMLButtonElement>("demo").disabled = value;
  $<HTMLButtonElement>("empty-demo").disabled = value;
  $("submit").textContent = value ? "正在读取来源…" : "开始调研 ↗";
  document.querySelector(".results")?.setAttribute("aria-busy", String(value));
  $("report").hidden = value || !current;
  $("empty").hidden = value || Boolean(current);
}
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = (await response.json()) as T & { error?: string };
  if (!response.ok)
    throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function references(ids: string[], item: Candidate): HTMLElement {
  const node = el("div", "step-references");
  if (!current) return node;
  const lookup = new Map<string, { label: string; url: string }>([
    ...item.sources.map((source) => [source.id, source] as const),
    ...current.report.documents.map(
      (doc) => [doc.id, { label: doc.path, url: doc.url }] as const,
    ),
    ...(current.report.policy?.findings ?? []).map(
      (row) =>
        [row.id, { label: `${row.path}:${row.line}`, url: row.url }] as const,
    ),
  ]);
  for (const id of ids) {
    const source = lookup.get(id);
    if (source) node.append(link(source.label + " ↗", source.url));
  }
  return node;
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
        current.report.candidates.length
          ? "当前筛选下没有候选。切换“全部”可查看其他协作状态。"
          : "本次没有找到符合筛选条件的候选。可以在“筛选与文件核实”中勾选“也看未匹配的问题”，或调整技术栈与目标仓库。",
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
    card.append(top, heading, meta, tags);
    if (!item.relevance)
      card.append(el("p", "match-reason", item.reasons.join(" · ")));
    if (item.relevance) {
      const match = el("div", `match-evidence ${item.relevance.kind}`);
      match.append(el("strong", "", item.relevance.label));
      const first = item.relevance.evidence[0];
      if (first)
        match.append(el("p", "", `${first.label}：${first.terms.join("、")}`));
      const body =
        first && ["问题正文", "原文路径的扩展名"].includes(first.label)
          ? first
          : undefined;
      if (body) match.append(el("blockquote", "", body.excerpt));
      else if (item.relevance.kind === "repository" && first)
        match.append(el("blockquote", "", first.excerpt));
      match.append(el("small", "", item.relevance.note));
      card.append(match);
    }
    if (item.policy_check) {
      card.append(
        el(
          "p",
          "policy-obligation",
          `贡献规则：待人工确认${!item.policy_check.documents_complete || !item.policy_check.contributing_found ? " · 文档缺失或读取不完整" : ` · ${item.policy_check.finding_count} 条原文线索`}。协作状态不代表贡献许可。`,
        ),
      );
    }
    if (item.risks.length) {
      const risks = el("div", "risk-box");
      risks.append(el("strong", "", "需要留意"), list(item.risks));
      card.append(risks);
    } else if (!item.policy_check) {
      card.append(
        el(
          "p",
          "quiet-note",
          "已读取范围内未发现占用或明确解决意图；普通引用单独列出，规则与源码仍待核实。",
        ),
      );
    }
    const details = el("details", "candidate-details") as HTMLDetailsElement;
    details.open = index === 0;
    details.append(el("summary", "", "查看证据与下一步"));
    const content = el("div", "detail-content");
    content.append(el("div", "mini-label", "建议下一步 · 有来源，未执行"));
    if (item.action_plan) {
      const steps = el("ol", "action-plan");
      for (const step of item.action_plan) {
        const row = el("li");
        row.append(
          el("strong", "", step.title),
          el("p", "", step.detail),
          references(step.source_ids, item),
        );
        steps.append(row);
      }
      content.append(steps);
    } else content.append(list(item.next_steps, "next-steps"));
    if (item.source_hints) {
      const paths = el("details", "source-paths");
      paths.append(
        el(
          "summary",
          "",
          `文件入口 · 已核实 ${item.source_hints.files.length} · 未核实 ${item.source_hints.unverified.length}`,
        ),
        el("p", "quiet-note", item.source_hints.note),
      );
      for (const file of item.source_hints.files)
        paths.append(
          link(file.path + " ↗", file.url),
          el("p", "quiet-note", file.note),
          el("pre", "source-excerpt", file.excerpt),
        );
      if (item.source_hints.unverified.length)
        paths.append(
          list(
            item.source_hints.unverified.map(
              (row) => `${row.path}：${row.reason}`,
            ),
          ),
        );
      if (item.source_hints.paths_omitted)
        paths.append(
          el(
            "p",
            "quiet-note",
            `另有 ${item.source_hints.paths_omitted} 个原文路径未展示，请阅读完整 issue。`,
          ),
        );
      content.append(paths);
    }
    if (item.reproduction || item.problem_evidence?.length) {
      const material = el("details", "problem-material");
      material.append(
        el("summary", "", "问题原文中的行为与代码摘录（未验证）"),
      );
      for (const section of item.problem_evidence ?? [])
        material.append(
          el("strong", "", section.label),
          el(
            "blockquote",
            "",
            section.text + (section.truncated ? "…（截断）" : ""),
          ),
        );
      if (item.reproduction)
        material.append(
          el("p", "quiet-note", item.reproduction.note),
          el(
            "pre",
            "source-excerpt",
            item.reproduction.text +
              (item.reproduction.truncated ? "\n…（截断）" : ""),
          ),
        );
      content.append(material);
    }
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
    item.sources
      .filter(
        (source) =>
          !["mention", "match", "file"].includes(source.category ?? ""),
      )
      .forEach((source) => {
        const block = el("div", "evidence");
        block.append(
          link(source.label + " ↗", source.url),
          el("blockquote", "", source.excerpt.slice(0, 700)),
        );
        content.append(block);
      });
    const mentions = item.sources.filter(
      (source) => source.category === "mention",
    );
    if (mentions.length) {
      const other = el("details", "ordinary-references");
      other.append(
        el("summary", "", `普通引用 · ${mentions.length} 条，不作为占用依据`),
      );
      for (const source of mentions)
        other.append(
          link(source.label, source.url),
          el("p", "quiet-note", source.excerpt),
        );
      content.append(other);
    }
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
        report.candidates.filter((item) => item.relevance?.kind === "direct")
          .length,
      ),
      "问题文本有匹配",
    ],
  ].forEach(([value, label]) => {
    const stat = el("div", "stat");
    stat.append(el("strong", "", value), el("span", "", label));
    stats.append(stat);
  });
  const selection = report.selection;
  $("selection-note").textContent =
    report.target?.mode === "issue"
      ? "指定问题模式：保留该 issue 并说明相关性。下方状态只描述协作线索，贡献规则需单独确认。"
      : `从 ${report.coverage.issues_scanned} 个问题中保留 ${report.candidates.length} 个候选${selection?.unmatched_excluded ? `，排除 ${selection.unmatched_excluded} 个未匹配的问题` : ""}。文本匹配、仓库语言和协作状态分别展示；候选数量是上限。`;
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
      "policy-obligation",
      "贡献规则尚未人工确认。此项独立于问题是否被认领、是否有关联解决方案。",
    ),
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
    if (result.request) {
      const request = result.request;
      $<HTMLInputElement>("repo").value = request.repo;
      $<HTMLInputElement>("stack").value = request.stack;
      $<HTMLSelectElement>("limit").value = String(request.limit);
      $<HTMLInputElement>("ai").checked = request.ai;
      $<HTMLInputElement>("include-unmatched").checked =
        request.include_unmatched;
      $<HTMLInputElement>("check-sources").checked = request.check_sources;
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
      $<HTMLInputElement>("include-unmatched").checked =
        result.report.selection?.include_unmatched ?? false;
      $<HTMLInputElement>("check-sources").checked =
        result.report.coverage.source_lookup_enabled ?? true;
      const requested = result.report.selection?.requested;
      if (!result.request && requested && [3, 5, 8].includes(requested)) {
        $<HTMLSelectElement>("limit").value = String(requested);
      }
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
        include_unmatched: $<HTMLInputElement>("include-unmatched").checked,
        check_sources: $<HTMLInputElement>("check-sources").checked,
      }),
    });
    remember(job.job_id);
    await waitForJob(job.job_id, started);
  } catch (error) {
    feedback(
      (error instanceof Error
        ? error.message
        : "网络请求失败，请确认本地服务仍在运行。") +
        (current ? " 下方仍为上一次报告，本次未生成新结果。" : ""),
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
    aiConfigured = config.ai_configured;
    $<HTMLInputElement>("ai").disabled = busy || !aiConfigured;
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
