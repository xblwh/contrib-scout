"""Classify references by observable intent; a mention is not a fix."""

import re


def prose_lines(text, with_offsets=False):
    fence = None
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_offset = offset
        offset += len(raw_line)
        line = raw_line.rstrip("\r\n")
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = (marker[1][0], len(marker[1]))
            elif marker[1][0] == fence[0] and len(marker[1]) >= fence[1]:
                fence = None
            continue
        if not fence and not line.lstrip().startswith(">"):
            yield (line_offset, line) if with_offsets else line


def reference_pattern(repo, number, same_repository=True):
    qualified = rf"(?<![\w/]){re.escape(repo)}#{number}(?!\d)"
    url = rf"https://github\.com/{re.escape(repo)}/issues/{number}(?!\d)"
    forms = [qualified, url]
    if same_repository:
        forms.append(rf"(?<![\w/])#{number}(?!\d)")
    return "(?:" + "|".join(forms) + ")"


def explicit_reference(pull, repo, number, same_repository=True):
    text = (pull.get("title") or "") + "\n" + (pull.get("body") or "")
    return bool(re.search(reference_pattern(repo, number, same_repository), text, re.I))


def solution_intent(pull, repo, number, same_repository=True):
    """Return a direct statement of intent, never claim automatic GitHub closure."""
    target = reference_pattern(repo, number, same_repository)
    pattern = re.compile(
        rf"(?:\b(?:close[sd]?|closing|fix(?:es|ed|ing)?|resolve[sd]?|resolving)\b|修复|解决)\s*(?:issue\s*)?[:：]?\s*{target}",
        re.I,
    )
    for line in prose_lines(pull.get("body") or ""):
        # Inline quoted syntax examples are not a declaration of work.
        line = re.sub(r"(`+)[^`]*\1", " ", line)
        for match in pattern.finditer(line):
            before = line[max(0, match.start() - 50) : match.start()]
            if re.search(
                r"(?:\bfor example\b|\bexample\s*:|\be\.g\.|例如|示例).{0,30}$",
                before,
                re.I,
            ):
                continue
            if re.search(
                r"\b(?:not|never|don't|doesn't|won't|cannot|can't)\b[^.;]*$|(?:不|不会|并非|示例).{0,12}$",
                before,
                re.I,
            ):
                continue
            return line.strip()[:500]
    title = pull.get("title") or ""
    if re.match(
        r"^(?:fix|feat|bugfix)(?:\([^)]*\))?!?:|^(?:修复|解决)", title, re.I
    ) and re.search(target, title, re.I):
        return title[:500]
    return None


def scope_reference(pull, repo, number, same_repository=True):
    """Refs/Related declares a relationship, but does not establish a fix."""
    target = reference_pattern(repo, number, same_repository)
    pattern = re.compile(
        rf"\b(?:refs?|references?|related(?:\s+to)?)\s*[:：]?\s*{target}", re.I
    )
    for line in prose_lines(pull.get("body") or ""):
        line = re.sub(r"(`+)[^`]*\1", " ", line)
        for match in pattern.finditer(line):
            before = line[max(0, match.start() - 50) : match.start()]
            if not re.search(
                r"(?:\bnot\b|\bnever\b|for example|\bexample\s*:|例如|示例).{0,30}$",
                before,
                re.I,
            ):
                return line.strip()[:500]
    return None


def hidden_cross_references(timeline, repo):
    count = 0
    for event in timeline:
        source = (event.get("source") or {}).get("issue") or {}
        if event.get("event") != "cross-referenced" or not source.get("pull_request"):
            continue
        url = source.get("html_url") or ""
        same = url.casefold().startswith(f"https://github.com/{repo.casefold()}/pull/")
        if not same and (source.get("repository") or {}).get("private") is not False:
            count += 1
    return count


def tokens(text):
    stopwords = {
        "this",
        "that",
        "with",
        "from",
        "when",
        "have",
        "does",
        "should",
        "support",
        "error",
        "issue",
        "fix",
        "test",
        "add",
    }
    return {
        x
        for x in re.findall(r"[a-z][a-z0-9_+-]{2,}", text.lower())
        if x not in stopwords
    }


def related_pulls(issue, pulls, timeline, repo):
    related = {}
    target_tokens = tokens(issue["title"])

    def add(pull, timeline_reference=False):
        url = pull.get("html_url", "")
        match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([1-9]\d*)", url)
        if not match:
            return
        source_repo = match[1]
        same = source_repo.casefold() == repo.casefold()
        # Timeline can include private sources visible to an authenticated viewer.
        if not same and (pull.get("repository") or {}).get("private") is not False:
            return
        intent = solution_intent(pull, repo, issue["number"], same)
        scope = scope_reference(pull, repo, issue["number"], same)
        reference = explicit_reference(pull, repo, issue["number"], same)
        other = tokens(pull.get("title", ""))
        overlap = len(target_tokens & other)
        similar = (
            same
            and overlap >= 2
            and overlap / max(1, len(target_tokens | other)) >= 0.35
        )
        if not (timeline_reference or reference or similar):
            return
        if intent:
            relation, label = "solution_intent", "作者提出解决意图"
        elif scope:
            relation, label = "scope_unconfirmed", "作者标注关联，范围待核实"
        elif similar:
            relation, label = "possible_overlap", "标题相似，待比较"
        else:
            relation, label = "mention", "普通引用，未发现解决意图"
        prior = related.get(url)
        merged = pull.get("merged_at") or (pull.get("pull_request") or {}).get(
            "merged_at"
        )
        kind = (
            "timeline"
            if timeline_reference
            else "reference"
            if reference
            else "similarity"
        )
        related[url] = {
            "number": int(match[2]),
            "repository": source_repo,
            "title": pull.get("title", ""),
            "url": url,
            "state": "merged" if merged else pull.get("state", "unknown"),
            "kind": prior["kind"] if prior else kind,
            "same_repository": same,
            "relation": relation,
            "relation_label": label,
            "intent_quote": intent,
            "scope_quote": scope,
            "reason": (
                "PR 正文或标题表明作者的解决意图；未确认自动关闭关联，是否解决仍需核对 diff。"
                if intent
                else "作者用 Refs/Related 标注关联；可能涉及部分范围，需要比较 diff，不能认定正在解决或已经解决。"
                if scope
                else "标题相似只提供可能重叠的线索。"
                if similar
                else "只记录引用来源，不据此认定占用或已解决问题。"
            ),
        }

    for event in timeline:
        source = (event.get("source") or {}).get("issue") or {}
        if event.get("event") == "cross-referenced" and source.get("pull_request"):
            add(source, True)
    for pull in pulls:
        add(pull)
    order = {
        "solution_intent": 0,
        "scope_unconfirmed": 1,
        "possible_overlap": 2,
        "mention": 3,
    }
    return sorted(
        related.values(),
        key=lambda pull: (
            order[pull["relation"]],
            pull["state"] != "open",
            pull["repository"],
            pull["number"],
        ),
    )
