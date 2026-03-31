"""Editorial system — formatting guides, style rules, and fact-checking agent.

This module defines:
1. FORMAT_GUIDE: per-category formatting rules (headers, bold, bullets, order)
2. ADAPTIVE_RULES: how to adjust structure based on content characteristics
3. fact_check(): background agent that verifies, enriches, and annotates synthesis
"""

import json
import logging
import os

from google import genai

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash"


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# ═══════════════════════════════════════════════════════════════
# UNIVERSAL FORMATTING RULES (apply to ALL categories)
# ═══════════════════════════════════════════════════════════════

UNIVERSAL_FORMAT = """
## Formatting System — Follow These Rules Exactly

### Header Hierarchy
- **## H2**: Major sections (e.g. "## What Actually Happened", "## Who's Affected")
  Always used for top-level section breaks. One blank line before, one after.
- **### H3**: Sub-sections within a major section (e.g. "### Bull Case", "### Bear Case")
  Used when a section has distinct parts. Don't overuse — max 2-3 per H2.
- Never use H1 (#) — that's reserved for the headline.
- Never go deeper than H3.

### Bold and Italic
- **Bold**: Use for exactly three things:
  1. Key terms on first mention: "The **Tensor G5** chip powers..."
  2. Crucial numbers: "Revenue hit **$4.2B**, up **23%**"
  3. The core insight in a paragraph (one per paragraph max): "The real story is **this changes who can afford to build AI products**"
- *Italic*: Use for exactly two things:
  1. Direct quotes: *"We didn't expect this result"*
  2. Emphasis on a single word for contrast: "This isn't *bad* — it's *irrelevant*"
- Never bold entire sentences. Never italic entire paragraphs.

### Bullet Points
- Use bullets (- ) for lists of 3+ parallel items
- Each bullet should be a complete thought, not a fragment
- Start each bullet with the most important word
- Pattern: **Key thing** — explanation of why it matters
  Example: **Context window: 1M tokens** — large enough to fit an entire medium codebase. Previously limited to 128K, which forced chunking.
- Max 8 bullets in a row. If you have more, group them under H3 sub-sections.
- Don't use bullets for narrative content — use paragraphs.

### Numbers
- Always pair a number with meaning: never "revenue was $4.2B" alone
- Pattern: **$4.2B revenue** (up 23% YoY, beating analyst estimates of $3.9B — the strongest quarter since 2022)
- Include: the number, the comparison, and what it means
- For percentages: always say what base it's a percentage OF
- Round intelligently: $4.237B → $4.2B. 23.4% → 23%. But keep precision when it matters (interest rate: 5.25%, not "about 5%")

### Paragraphs
- 2-4 sentences each. Never more than 5.
- First sentence: the point of this paragraph
- Remaining sentences: evidence, context, or nuance
- Last paragraph of each section: the "so what" — why this matters
- One idea per paragraph. If you're covering two things, split.

### Transitions
- Don't use: "Furthermore," "Additionally," "Moreover," "It's worth noting"
- Do use: direct connections — "This explains why..." / "But there's a catch:" / "The flip side:"
- Or just start the next section. No transition needed between H2 sections.

### Quotes
- Use > blockquote for direct quotes longer than 10 words
- Short quotes inline with *italics*
- Always attribute: who said it and why they're credible

### Length
- Layer 1 (summary): 150-250 words + 6-10 bullet key points
- Layer 2 (deep read): 1000-1500 words (3-5 minute read at 300wpm)
- If content doesn't warrant full length, be shorter. Don't pad. 800 words of substance > 1500 words of filler.
"""

# ═══════════════════════════════════════════════════════════════
# PER-CATEGORY FORMAT GUIDES
# ═══════════════════════════════════════════════════════════════

CATEGORY_FORMAT = {
    "ai": """
### AI Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What Changed — facts only, no adjectives. Bold the product/model name on first mention.
2. ## Why This Actually Matters (Or Doesn't) — the core section. Use before/after examples in bold.
   Pattern: **Before:** [old way]. **After:** [new way]. **In practice:** [reality check].
3. ## The Numbers In Context — every number gets a bullet with context:
   - **1M token context** — equivalent to ~750K words. Previously 128K. *This means:* whole-codebase analysis without chunking.
4. ## What To Actually Do — numbered list of specific steps. Use code blocks for commands.
5. ## What's Still Missing — honest gaps. Use ⚠️ prefix for each.

**Bullet style for this category:**
- 🔧 **Tool name** — what it does, what it replaces
- 📊 **Number** (context) — *which means:* practical implication
- ⚡ **Change** — why significant / why overhyped
""",

    "tech": """
### Tech Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What Is It — 3 sentences max. **Product name**, maker, **price**, date. Period.
2. ## The Real Story — 2-3 paragraphs. Lead each with a bold claim, follow with evidence.
   Pattern: **[Claim]**. In testing, [specific result]. Compared to [competitor], [comparison]. *This matters because* [why].
3. ## Numbers That Matter — use a structured list:
   - **Spec name: value** — ✅ matters because [reason] / ❌ marketing fluff because [reason]
   Compare every number to: the thing it replaces + the main alternative.
4. ## Who This Is For — bold each user type, then explain:
   **Video editors** who currently use [X] → this solves [specific problem]. Worth upgrading.
   **Casual users** → the $300 cheaper [model] does 90% of this.
5. ## The Catch — bullet list with ⚠️ prefix for each honest downside.

**Never do:** Repeat the spec sheet without annotation. Every number needs "which means..."
""",

    "podcasts": """
### Podcast Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## Who Is This Person — NOT a bio. A narrative setup.
   Pattern: **[Name]** [one-line identity]. [What they built/survived]. [Why that makes their view on [topic] worth hearing].
   2-3 sentences. Make the reader curious about this person.
2. ## The Core Message — one bold paragraph stating the thesis. Then 1-2 paragraphs of WHY they believe it.
3. ## The Stories — this section should be the LONGEST (40% of word count).
   For each story use this format:
   ### [Story title — descriptive, not generic]
   *[Setup in italic — when, where, what was at stake]*
   [The story itself in regular text — 2-3 paragraphs with detail]
   **The lesson:** [bold one-line takeaway]
4. ## Frameworks & Mental Models — for each:
   ### [Framework name in bold]
   **What it is:** [1 sentence definition]
   **When to use it:** [specific trigger/situation]
   **Their example:** [how the speaker used it]
   **Try this:** [how the reader can apply it this week]
5. ## What To Do Differently — numbered list, each starting with a verb
6. ## The Quotes — blockquote format (> ), 3-4 quotes, each followed by 1 line of context

**Key rule:** Stories are the product. Don't abbreviate them. Retell with enough detail that the reader gets the full insight.
""",

    "economics": """
### Economics Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What Happened — lead with the **bold number**. First sentence = the fact. Second = the context.
   Pattern: **[metric] came in at [number]**, [comparison to expectation]. This is the [Nth time / highest since / etc.].
2. ## What The Numbers Actually Mean — the core section. For each number:
   - **[Number]** ([comparison]) — *In plain terms:* [what this means for a normal person]
   Use specific examples: "A 0.25% rate hike on a $400K mortgage = **$67/month more**"
3. ## Who Wins, Who Loses — use bold H3 sub-sections:
   ### Winners
   - **[Group]** — [why, with specifics]
   ### Losers
   - **[Group]** — [why, with specifics]
   ### The Overlooked
   - **[Group no one's discussing]** — [why they matter]
4. ## The Debate — use H3 for each side:
   ### The Case For [X]
   ### The Case Against [X]
   End with: *What would prove each side right:* [specific indicators]
5. ## What To Watch — bullet list with dates and specific triggers

**Number formatting rule:** Never a naked number. Always: **number** (comparison) — meaning.
""",

    "crypto": """
### Crypto Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What Happened — price action with context. Bold key levels.
   Pattern: **[Asset]** moved [direction] to **[price]** ([%]), [timeframe]. This [is/isn't] significant because [volume/technical/fundamental reason].
2. ## The Real Catalyst — go past "sentiment." Specific event → specific impact.
   Use **bold** for the catalyst name, then unpack it.
3. ## Adoption Reality Check — two-column mental model:
   **Real signal:** [metric that matters] — [what it shows]
   **Noise:** [metric that doesn't matter] — [why it's misleading]
4. ## Regulatory Landscape — status tags in bold:
   **PROPOSED** / **COMMENTED** / **FINALIZED** / **ENFORCED** — [what, where, implications]
5. ## Risk Assessment — bullet list, each with:
   ⚠️ **[Risk type]** (likelihood: [low/medium/high]) — [what triggers it, what happens]

**Key rule:** Distinguish signal from noise explicitly. Use "Real signal" vs "Noise" framing throughout.
""",

    "science": """
### Science Category — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What They Found — two-part structure:
   **The finding:** [technical statement in bold]
   **In plain language:** [what a non-scientist should understand]
2. ## How They Did It — explain for a smart non-expert:
   - **Method:** [what they did, analogized if helpful]
   - **Scale:** [sample size, duration] — *This is [adequate/small/large] because [reason]*
   - **Controls:** [what they compared to]
3. ## Why This Matters (Honestly) — the hype check section:
   **Headlines say:** [the hyped version]
   **The paper actually shows:** [the real version]
   **The gap:** [what's being exaggerated or undersold]
   Include honest timeline: *"Lab discovery → clinical use typically takes [X] years. This is at stage [Y]."*
4. ## The Bigger Picture — connections to the field. Use *italic* for study names/years.
5. ## What To Watch — bullet list of: replication status, next experiments, open questions

**Key rule:** Two-voice pattern — state the technical finding, then immediately translate it. Never leave jargon unexplained.
""",

    "korean_news": """
### 한국 뉴스 — 섹션 순서 & 포맷팅

**섹션 순서 (Layer 2):**
1. ## 실제로 무슨 일이 일어났나 — 팩트만. 프레이밍 제거. **굵은 글씨**로 핵심 사실 강조.
2. ## 언론사별 보도 분석 — H3로 각 매체 구분:
   ### 보수 매체 (조선·중앙)
   ### 진보 매체 (한겨레·경향)
   ### 경제지 (한경·매경)
   각각: 어떤 프레임? 뭘 강조? 뭘 축소? **이 차이가 의미하는 것:**
3. ## 누가 영향 받나 — 구체적 집단별 굵은 글씨:
   **자영업자** — [구체적 영향과 이유]
   **청년층** — [구체적 영향과 이유]
4. ## 헤드라인 너머 — 기사들이 빠뜨린 맥락. *기울임체*로 과거 유사 사례 인용.
5. ## 앞으로의 전개 — 구체적 날짜와 관전 포인트 불릿 리스트.

**숫자 규칙:** **숫자** (비교 대상) — 의미. 맨숫자 금지.
""",

    "world_news": """
### World News — Section Order & Formatting

**Section Order (Layer 2):**
1. ## What Actually Happened — facts stripped of framing. Bold key facts.
2. ## How It's Being Covered — use H3 for each perspective:
   ### Western Media (Reuters, BBC, CNN)
   ### Regional/Local Media
   ### State Media / Official Narrative
   For each: what's emphasized, what's minimized, **what the framing reveals about their interests**.
3. ## Who's Really Affected — bold each group:
   **[Specific group]** — [concrete impact, with numbers if available]
   Separate: direct victims, beneficiaries, overlooked groups.
4. ## The Bigger Picture — bold the historical parallel:
   **The last time [similar event]** was [date], and what followed was [outcome].
5. ## What to Watch — bullet list with dates and trigger conditions.

**Key rule:** Name specific groups, not abstractions. Not "civilians" but "the 2.3M residents of [area] who..."
""",
}

# ═══════════════════════════════════════════════════════════════
# ADAPTIVE FORMATTING RULES
# ═══════════════════════════════════════════════════════════════

ADAPTIVE_RULES = """
## Content-Adaptive Formatting

Adjust your approach based on what the content contains:

### If there are MULTIPLE SOURCES on the same topic:
- Add a "### How Sources Differ" sub-section
- Use this format for each point of difference:
  **[Topic]:** Source A says [X]. Source B says [Y]. *The difference matters because:* [Z].
- Bold the areas of agreement: **All sources confirm that...**

### If the content is NUMBERS-HEAVY (economics, earnings, data):
- Lead every section with the key number in bold
- Use comparison triplets: **[number]** (vs [expectation] / vs [previous] / vs [competitor])
- End with: *Bottom line:* [one sentence plain-language meaning]

### If the content is NARRATIVE-HEAVY (podcasts, interviews, profiles):
- Stories get more space — 40% of word count minimum
- Use *italic* for scene-setting and direct quotes
- Use **bold** for the lesson/insight from each story
- Include speaker's exact words when powerful

### If the content is a CONTROVERSY or DEBATE:
- Present strongest version of each side (steel-man, don't straw-man)
- Use H3 headers for each position: ### The [X] Argument / ### The [Y] Argument
- End with: *What would settle this:* [specific evidence or event]

### If the content is TECHNICAL (AI, crypto protocol, science methodology):
- Use code blocks (```) for commands, configs, API examples
- Use **bold** for technical terms on first appearance, then normal text
- Pattern: **[Term]** (also called [alias]) — [plain-language definition]. [Why it matters for you].

### If the content is BREAKING or TIME-SENSITIVE:
- Lead with: ⚡ **[Time] — [Event]**
- Separate confirmed facts from developing claims
- Use ⚠️ for unverified information: ⚠️ *Unverified:* [claim] (reported by [source only])
"""


# ═══════════════════════════════════════════════════════════════
# FACT-CHECKING AGENT
# ═══════════════════════════════════════════════════════════════

FACT_CHECK_PROMPT = """You are a fact-checking and enrichment editor. You receive a synthesized article and the original source material.

Your job is NOT to rewrite. Your job is to:

1. **VERIFY claims**: Check if the synthesis accurately represents what the sources say. Flag any:
   - Misquoted or paraphrased inaccurately
   - Numbers that don't match the source
   - Claims attributed to the wrong source
   - Exaggerations or understatements

2. **ADD context**: For key claims, add relevant context the synthesis missed:
   - Historical precedent ("The last time this happened was...")
   - Scale/comparison ("To put this in perspective, X is equivalent to...")
   - Counter-evidence ("However, [other study/expert] found...")
   - Missing stakeholder perspective

3. **ANNOTATE numbers**: For every number in the synthesis:
   - Verify it matches the source
   - Add comparison if missing (vs previous, vs expected, vs baseline)
   - Flag if the number is misleading without context

4. **FLAG uncertainty**: Mark claims by confidence:
   - ✅ CONFIRMED — multiple sources agree, verifiable fact
   - ⚠️ SINGLE SOURCE — only one outlet reports this
   - ❓ UNVERIFIED — claim made but no evidence provided
   - 🔄 DEVELOPING — situation is ongoing, facts may change

Return JSON:
{
    "corrections": [
        {"original": "text in synthesis", "issue": "what's wrong", "fix": "corrected version"}
    ],
    "additions": [
        {"after_section": "section header", "content": "additional context to insert", "type": "context|comparison|counter|perspective"}
    ],
    "number_checks": [
        {"number": "the number", "source_says": "what source actually says", "status": "correct|wrong|missing_context", "context_to_add": "comparison or context"}
    ],
    "confidence_flags": [
        {"claim": "the claim", "confidence": "confirmed|single_source|unverified|developing", "reason": "why"}
    ],
    "enrichments": [
        {"topic": "what this relates to", "detail": "additional useful information", "source": "where this comes from"}
    ]
}"""


async def fact_check(synthesis_text: str, source_texts: list[str],
                     category: str) -> dict:
    """Run fact-checking agent on synthesized content.

    Returns enrichment data that can be merged into the final output.
    """
    sources_combined = "\n\n---\n\n".join(
        f"SOURCE {i+1}:\n{s[:3000]}" for i, s in enumerate(source_texts)
    )

    prompt = f"""{FACT_CHECK_PROMPT}

CATEGORY: {category}

SYNTHESIS TO CHECK:
{synthesis_text[:6000]}

ORIGINAL SOURCES:
{sources_combined[:8000]}

Return the JSON analysis."""

    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        text = resp.text.strip()
        # Extract JSON
        if "```" in text:
            parts = text.split("```")
            for part in parts[1::2]:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("{"):
                    return json.loads(cleaned)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
    except Exception as e:
        logger.warning("Fact-check agent failed: %s", e)

    return {"corrections": [], "additions": [], "number_checks": [],
            "confidence_flags": [], "enrichments": []}


def apply_fact_check(synthesis_text: str, fact_check_result: dict) -> str:
    """Merge fact-check results into the synthesis text."""
    text = synthesis_text

    # Apply corrections
    for correction in fact_check_result.get("corrections", []):
        original = correction.get("original", "")
        fix = correction.get("fix", "")
        if original and fix and original in text:
            text = text.replace(original, fix)

    # Add confidence flags as inline annotations
    for flag in fact_check_result.get("confidence_flags", []):
        claim = flag.get("claim", "")
        confidence = flag.get("confidence", "")
        if claim and confidence and claim in text:
            icon = {"confirmed": "✅", "single_source": "⚠️",
                    "unverified": "❓", "developing": "🔄"}.get(confidence, "")
            if icon and icon not in text.split(claim)[0][-5:]:
                text = text.replace(claim, f"{icon} {claim}", 1)

    # Append enrichments at the end if substantive
    enrichments = fact_check_result.get("enrichments", [])
    additions = fact_check_result.get("additions", [])

    if enrichments or additions:
        extras = []
        for e in enrichments:
            if e.get("detail"):
                extras.append(f"- {e['detail']}")
        for a in additions:
            if a.get("content") and a.get("type") in ("context", "counter", "comparison"):
                extras.append(f"- {a['content']}")

        if extras:
            text += "\n\n### Additional Context\n" + "\n".join(extras[:5])

    return text


def get_format_instructions(category: str) -> str:
    """Get the complete formatting instructions for a category."""
    cat_format = CATEGORY_FORMAT.get(category, "")
    return f"{UNIVERSAL_FORMAT}\n\n{cat_format}\n\n{ADAPTIVE_RULES}"
