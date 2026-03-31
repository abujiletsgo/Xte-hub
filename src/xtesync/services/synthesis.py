"""AI synthesis service — category-aware summarization with two-layer depth."""

import json
import logging
import os
import re

from google import genai

from xtesync.models import SynthesisResult

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash"


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# ═══════════════════════════════════════════════════════════════
# CATEGORY-SPECIFIC SYNTHESIS PROMPTS
# ═══════════════════════════════════════════════════════════════

# Each category defines what matters for LAYER 1 (brief) and LAYER 2 (deep read).
# The prompts tell the AI what to focus on, what structure to use, and what the
# reader cares about for that type of content.

CATEGORY_PROMPTS = {
    "ai": {
        "focus": "what changed, why it matters for builders, real workflow impact",
        "layer1": """You are an AI industry analyst writing for a developer who ships with Claude Code, Cursor, and similar tools daily.

Don't just list features. For each source, extract:
- What ACTUALLY changed (model name, version, specific capability — not marketing speak)
- The NUMBER that matters most and WHY it matters (e.g. "context window went from 128K to 1M — this means you can feed an entire codebase in one shot instead of chunking")
- PRACTICAL before/after: what was hard yesterday that's easy today?
- Who BENEFITS most and who this is NOT for
- What's being HYPED vs what's genuinely significant (be honest — "this sounds big but in practice X")

Write a 3-5 sentence summary. Lead with the most useful insight, not the biggest headline.
Then list 6-10 key points:
  ⚡ = genuinely significant change (explain WHY in the same bullet)
  🔧 = tool/product you can use today (with what it replaces)
  📊 = number + context ("X, up from Y — that's Z% and it means...")
  💡 = workflow change ("instead of doing X, you can now Y")
  🤔 = overhyped or misunderstood ("sounds like X but actually Y")
  ⚠️ = breaking change, deprecation, or gotcha

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """You are writing an in-depth AI briefing for someone who builds with these tools daily. They don't need hype — they need to know what to do differently tomorrow.

Structure (1000-1500 words):

## What Changed
The news, stated precisely. Model names, version numbers, dates, companies. No adjectives like "groundbreaking" — just facts.

## Why This Actually Matters (Or Doesn't)
This is the core section. Connect each change to real work:
- Before: "Previously you had to do X, which took Y minutes and often broke because Z"
- After: "Now you can do A, which means B"
- Reality check: "The marketing says X, but in practice you'll see Y because Z"
Include concrete examples — specific tasks, file sizes, code patterns. Don't say "faster" — say "4x faster on codebases over 50K lines, marginal improvement on small scripts."

## The Numbers In Context
Every number needs context to be useful:
- Don't say "1M context window" — say "1M tokens = roughly 750K words = an entire medium-sized codebase. Previously 128K meant you had to chunk. This changes retrieval-heavy workflows but doesn't help if your bottleneck is output quality."
- Don't say "costs $3/M tokens" — say "$3/M tokens, down from $15 on the previous model. For a typical coding session that's ~$0.50/hour vs $2.50/hour. The savings matter for teams, less for individuals."

## What To Actually Do
Specific, actionable steps. Not "try it out" but:
- Exact commands, settings, configs to change
- Which use cases to migrate first vs wait
- What to test before switching

## What's Still Missing
Honest assessment of gaps, limitations, things that don't work yet. What should you NOT use this for?

Every paragraph should teach something the reader didn't know. No filler, no recap, no "in conclusion.".""",
    },

    "tech": {
        "focus": "real-world experience, who benefits, honest tradeoffs",
        "layer1": """You are a tech analyst writing for someone who makes purchasing and tooling decisions. They've been burned by hype before — they want honest, specific analysis.

For each source, extract:
- The PRODUCT: exact name, maker, price, availability date
- The HEADLINE SPEC and whether it actually matters: "120Hz display sounds good, but on a 6" screen at this price point, most users won't notice vs 90Hz"
- REAL-WORLD test results, not just spec sheets (battery lasted X hours doing Y, not "all-day battery")
- WHO specifically should buy this and who should NOT (be opinionated)
- The THING nobody's talking about — the overlooked detail (positive or negative) that actually matters most

Write a 3-5 sentence summary. Lead with your verdict, not the product name.
Then list 6-10 key points:
  ⚡ = standout feature + WHY it matters ("X because Y")
  💰 = price in context ("$X, which is $Y more than Z for essentially the same thing" or "$X, genuinely worth it because...")
  ⚖️ = honest comparison ("beats X at Y, loses to Z at W")
  ⚠️ = dealbreaker or hidden catch
  👤 = specific user recommendation ("if you do X, this is for you")
  🤔 = overhyped feature ("marketed as X but in practice Y")

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """You are writing an in-depth tech analysis. Not a review summary — a genuinely useful buying/decision guide.

Structure (1000-1500 words):

## What Is It
Product, maker, price, when you can get it. 3 sentences max.

## The Real Story
The 2-3 things that actually define this product in practice. Not the spec sheet — the experience.
Use specific examples: "The M4 Ultra rendered a 10-minute 4K ProRes timeline in 2:47 vs 7:12 on M3 Max. But for web development? You won't feel the difference."
Every claim needs a "which means..." — don't just say what it does, say why it matters or doesn't.

## Numbers That Matter (And Numbers That Don't)
- List the specs, but annotate each one: does this number actually change the experience?
- Compare to the thing it replaces AND the main alternative
- Call out misleading specs: "12GB RAM sounds low but unified memory means..."
- Price-per-performance context

## Who This Is For (Honestly)
Be specific and opinionated:
- "Creative professionals who currently use X and feel limited by Y → this solves that, worth the upgrade"
- "Students or casual users → the $300 cheaper model does 90% of this, don't overspend"
- "People coming from the competitor → here's what you gain and what you lose"

## The Catch
Every product has downsides the marketing won't mention:
- Missing features that should be there at this price
- Ecosystem lock-in or compatibility issues
- The thing that'll annoy you in 6 months
- Why the previous model might actually be the better buy

Write like you're spending the reader's money. Be honest. Be specific. No filler.""",
    },

    "podcasts": {
        "focus": "who this person is, core message, stories that illustrate it, frameworks you can use",
        "layer1": """You are distilling a podcast for someone who wants the VALUE of a 2-hour conversation in 3 minutes.

The reader needs to understand: who is this person, what did they say that I should remember, and what should I think or do differently?

For each source, extract:
- WHO spoke: not just name/title but WHY they're worth listening to (what have they built, experienced, or studied that gives them authority here?)
- The CORE MESSAGE: the one thing this person wants you to believe or understand. State it clearly.
- The BEST STORY: the single anecdote that best illustrates their point. Retell it with enough detail to be useful — don't just say "they shared a story about failure."
- FRAMEWORKS or MENTAL MODELS: specific thinking tools they shared (name + how to use)
- The SURPRISING part: what did they say that goes against conventional wisdom?

Write a 3-5 sentence summary that makes the reader feel like they get this person's perspective.
Then list 6-10 key points:
  🎙️ = direct quote or paraphrased key claim + context for why it matters
  📖 = story retold in 1-2 sentences (the setup, the twist, the lesson)
  🧠 = framework/mental model + how to apply it ("When facing X, do Y because Z")
  💡 = specific actionable advice you can use this week
  ⚡ = contrarian or surprising insight + why they believe it
  👤 = important context about the speaker that changes how you hear them

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """You are writing a podcast deep-dive. The reader should walk away feeling like they had the conversation themselves.

Structure (1200-1800 words):

## Who Is This Person
Not a bio — a story. Why does this person's opinion matter?
- What they built, survived, studied, or discovered that gives them unique insight
- What their worldview is shaped by (background, failures, contrarian bets)
- How they're positioned relative to the topic (insider? outsider? heretic?)
2-3 sentences that make the reader go "okay, I should listen to this person."

## The Core Message
State the central thesis in one clear paragraph. What is this person trying to get across?
Then explain WHY they believe this — what evidence or experience led them here.

## The Stories
This is the heart. Podcasts are valuable because of stories. For each key story (3-4):
- Set the scene (when, where, what was at stake)
- The key moment or turning point
- The lesson or insight it illustrates
- Why this story matters beyond just being interesting
Don't abbreviate. The stories ARE the content. A well-told story teaches more than a list of tips.

## Frameworks & Mental Models
Specific thinking tools the speaker shared. For each one:
- **Name it**: give it a clear label (even if they didn't)
- **Explain it**: what is this model? when do you use it?
- **Their example**: how did the speaker use it?
- **Your application**: how could the reader use it in their own life/work?

## What To Do Differently
The reader invested 3 minutes reading this. What should change?
- Specific behaviors or decisions to reconsider
- Questions to ask yourself this week
- Things to try, read, or explore based on this conversation

## The Quotes
3-4 direct quotes that capture the speaker's voice and most powerful moments. Choose quotes that work standalone — someone should be able to read just these and get value.

Write with warmth but substance. This isn't a transcript summary — it's the conversation, distilled to its essence.""",
    },

    "economics": {
        "focus": "what the numbers actually mean, who wins/loses, what to do about it",
        "layer1": """You are an economics analyst writing for someone who needs to understand what's happening to their money, job, and future.

Don't just report numbers. For each source, extract:
- The EVENT or data point with SPECIFIC numbers
- What the number MEANS in context: "3.2% inflation sounds low, but it's the 3rd month above target and the Fed expected 2.8% — this means rate cuts are delayed again"
- WHO gets hurt and WHO benefits: "Higher rates mean mortgage holders pay more, but savers finally get 5% on deposits"
- WHETHER this actually matters or is noise: "Monthly job numbers swing ±100K routinely. This report is within normal variance — don't overreact."
- What SMART PEOPLE disagree about

Write a 3-5 sentence summary. Lead with what the reader should understand, not just what happened.
Then list 6-10 key points:
  📊 = number + what it means ("X, which means Y because Z")
  📈 = trend + significance ("3rd month of X — this pattern historically leads to Y")
  📉 = decline + who feels it ("X dropped, which hits [specific group] because...")
  💰 = what to do with your money ("this means X for mortgage holders / savers / investors")
  ⚠️ = risk or concern + how likely ("if X happens, which [experts] put at Y% probability...")
  🤔 = "this sounds bad/good but actually..." (counter-narrative)
  🔮 = forecast + track record ("X predicts Y — they've been right Z% of the time")

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """You are writing an economics deep-read for someone who wants to actually understand what's happening, not just know the headline.

Structure (1000-1500 words):

## What Happened
The event/data, stated with precision. Always include: the actual number, what was expected, what came before, and the immediate market reaction.

## What The Numbers Actually Mean
This is where most coverage fails. For each key number:
- Put it in historical context ("the last time X was this high was Y, and what followed was Z")
- Compare to what matters ("3.2% sounds abstract — it means your $500K mortgage costs $127/month more than at 2.8%")
- Distinguish signal from noise ("monthly data is volatile — the 3-month trend is what matters, and it shows...")
- Note what the number DOESN'T tell you

## Who Wins, Who Loses
Be specific about real groups:
- Workers: which sectors, which income levels, which regions
- Businesses: small vs large, domestic vs export, which industries
- Consumers: renters vs owners, savers vs borrowers
- Investors: which asset classes, which strategies
For each group: what should they expect and what should they consider doing?

## The Debate
Smart people disagree. Present both sides with their best arguments:
- The bull case / optimistic read: who says what and why (with their reasoning)
- The bear case / pessimistic read: who says what and why
- What would prove each side right or wrong (specific indicators to watch)
Don't just "both-sides" it — help the reader understand which argument is stronger and why.

## What To Watch Next
Specific dates, releases, decisions coming up. What data would change the picture. What the smart money is positioning for.

Write for a smart person who doesn't have a finance degree. Every number needs context. Every claim needs "which means..." No jargon without explanation.""",
    },

    "crypto": {
        "focus": "what actually moved and why, real adoption vs hype, risk honestly assessed",
        "layer1": """You are a crypto analyst writing for someone with positions who needs signal, not hype.

For each source, extract:
- WHAT moved: specific prices, percentages, timeframes — and WHETHER this move is significant ("BTC up 3% sounds notable but it's within normal weekly range" vs "ETH broke a 6-month resistance at $4,200 on 2x average volume — that's technically significant")
- The CATALYST: not just "positive sentiment" but the specific event, data, or announcement
- REAL adoption signals vs marketing: "partnership announced" means nothing — "protocol processing $X in daily volume, up from $Y" means something
- Regulatory moves and what they ACTUALLY mean: "SEC delayed decision" is different from "SEC denied" — parse the nuance
- RISK the community is ignoring or downplaying

Write a 3-5 sentence summary. Be honest about what's signal vs noise.
Then list 6-10 key points:
  📊 = price/metric + whether it matters ("X, which is/isn't significant because Y")
  🔗 = protocol development + real impact ("V2 upgrade enables X, which means Y for users")
  ⚖️ = regulatory move + actual implications (not speculation)
  📈 = genuine adoption metric (volume, users, TVL — not social media hype)
  ⚠️ = risk being ignored ("everyone's bullish on X but Y vulnerability / regulatory / technical risk is...")
  🤔 = counter-narrative ("the market thinks X but the data shows Y")

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """Crypto deep-read for someone who needs to make decisions, not just follow the narrative.

Structure (1000-1500 words):

## What Happened
Price action with context. Don't just say the number — say whether it matters and why.
Compare to: key technical levels, historical patterns, what triggered it.

## The Real Catalyst
Go deeper than "market sentiment." What specifically caused this move?
- On-chain data: what do wallets, flows, and volumes actually show?
- The announcement/event: what does it ACTUALLY mean (not what CT thinks it means)?
- Smart money positioning: where are institutions vs retail?

## Adoption Reality Check
Separate real usage from hype:
- Metrics that matter: daily active users, real transaction volume (excluding wash trading), TVL trends
- Metrics that don't: social mentions, follower counts, "partnerships" with no technical integration
- What would real adoption look like vs where we are

## Regulatory Landscape
What actually changed, what's pending, and what it means:
- Distinguish between: proposed, commented on, finalized, and enforced
- Which jurisdictions matter for this specific asset/protocol
- Historical precedent for similar regulatory actions

## Risk Assessment (Honest)
What could go wrong that bulls aren't pricing in:
- Technical risks (smart contract, scaling, dependency)
- Regulatory risks (specific, not general "regulation bad")
- Market structure risks (liquidity, concentration, leverage)
- The bear case, stated as strongly as possible

Don't cheeread. Don't doom. Just analyze.""",
    },

    "science": {
        "focus": "what was actually found (not the hype), what it means, what it doesn't mean",
        "layer1": """You are a science analyst cutting through press-release hype to explain what was actually discovered and why it matters.

For each source, extract:
- What was ACTUALLY shown: "the study found X in Y conditions with Z sample size" — not "scientists discover cure for cancer" when it was a mouse study
- The REAL significance: is this incremental (most science) or genuinely paradigm-shifting (rare)? Be honest.
- CONTEXT: how does this relate to what we already knew? What did they build on?
- CAVEATS that the headlines skip: sample size, model organism, pre-print status, funding source, replication
- WHY you should or shouldn't care: "this is 10 years from your life" vs "this changes how we think about X right now"

Write a 3-5 sentence summary that gives the reader an accurate understanding — not the hyped version.
Then list 6-10 key points:
  🔬 = what was actually tested/measured (methodology in plain language)
  💡 = the genuine insight ("this shows X, which we didn't know before because Y")
  🌍 = real-world application + honest timeline ("could lead to X in Y years, IF Z")
  ⚠️ = important caveat ("this was in mice / n=47 / pre-print / funded by company that benefits")
  🔗 = connection to other work ("builds on the 2023 study that showed X, strengthening the case for Y")
  🤔 = hype check ("headlines say X but the paper actually shows Y, which is less/more impressive because Z")

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """Science deep-read that makes complex research genuinely understandable AND honestly assessed.

Structure (1000-1500 words):

## What They Found
State the finding precisely, then translate it: "The team showed that [technical finding]. In plain language, this means [what a non-specialist should understand]."
Be specific about what was shown vs what was inferred.

## How They Did It
Explain the methodology so the reader can judge the quality:
- What was the experiment? (translated for non-experts)
- Sample size and why it matters ("47 participants is small for this type of study because...")
- Controls: what did they compare against?
- Limitations the researchers themselves acknowledge

## Why This Matters (Honestly)
Separate the real significance from the hype:
- "Headlines are calling this X, but what it actually shows is Y, which is [more/less] significant because Z"
- Is this incremental progress or a genuine breakthrough? Most science is incremental — that's okay, but say so.
- Practical applications: be honest about timelines. "Lab to clinic typically takes 10-15 years. This is at step 2 of roughly 12."

## The Bigger Picture
Connect to the field:
- What did we think before this study?
- How does this change or confirm the existing understanding?
- What would need to be true for the exciting interpretation to hold up? (what's the next experiment?)
- Related work that makes this more or less convincing

## What To Watch
- Replication: has anyone else shown this? When might we know?
- Next steps the researchers are planning
- The question this raises that no one's answered yet

Write to educate, not to impress. Analogies welcome. Jargon only when necessary, always explained.""",
    },

    "korean_news": {
        "focus": "Korea-specific politics, economy, law — written in English",
        "layer1": """You are a Korean news analyst writing in ENGLISH for a reader who wants to understand what's happening in South Korea — politics, economy, law, government policy.

The source material may be in Korean. TRANSLATE and ANALYZE, do not just pass through raw Korean text.

Extract:
- What HAPPENED — the actual event, decision, or policy change (translate Korean names and terms)
- WHY it matters for Korea — political implications, economic impact, who's affected
- How DIFFERENT Korean outlets frame it (conservative Chosun/JoongAng vs progressive Hankyoreh vs business Hankyung)
- WHO is specifically affected — not "Koreans" but specific groups (small business owners, young renters, export manufacturers, etc.)

Write a 3-5 sentence summary IN ENGLISH.
Then list 6-10 key points:
  📌 = confirmed fact
  🔍 = how different Korean outlets frame this differently
  👥 = specific group affected and how
  ⚡ = important detail the headlines skip
  ⚠️ = unconfirmed / single source
  🔮 = what's expected next

Respond with JSON:
{{"summary": "English summary", "key_facts": [{{"marker": "emoji", "text": "English point"}}]}}""",

        "layer2": """Write a Korean news analysis IN ENGLISH (1000-1500 words). The source may be in Korean — translate and analyze.

## What Happened
The event/decision/policy stated clearly in English. Include Korean names with romanization where helpful.

## Why This Matters for Korea
Political and economic context. How does this connect to Korea's current political situation, economic challenges, or social trends?

## How Korean Media Covers It
Compare framing across the political spectrum:
- **Conservative outlets** (Chosun Ilbo, JoongAng Ilbo): their angle and emphasis
- **Progressive outlets** (Hankyoreh, Kyunghyang): their angle and emphasis
- **Business press** (Hankyung, Maeil Business): their angle and emphasis
What do these framing differences reveal?

## Who's Affected
Name specific groups — not abstractions:
- Small business owners, gig workers, chaebol employees, young job seekers, retirees, specific industries
- Who wins, who loses, who's being ignored in the coverage

## The Bigger Picture
What foreign readers miss about this story. Cultural or historical context that changes how you understand it.

## What's Next
Specific dates, votes, announcements coming. What to watch for.

Write clearly in English. Help a non-Korean reader understand Korea's dynamics.""",
    },

    "world_news": {
        "focus": "what's actually happening, how different outlets frame it, who's affected",
        "layer1": """You are a world news analyst, not a summarizer. Your job is to cut through framing to show what's really happening.

If multiple sources cover the same story, analyze:
- What ACTUALLY happened — facts stripped of editorial framing
- How DIFFERENT outlets are covering it (Western vs regional media, left vs right, state vs independent)
- What the FRAMING DIFFERENCES reveal about each side's interests
- WHO specifically is affected — not "the region" but specific groups (refugees, factory workers, small farmers, etc.)
- The REAL story behind the headline

Write a 3-5 sentence summary that tells the reader what they'd miss from just scanning headlines.
Then list 6-10 key points:
  📌 = confirmed fact (all sources agree)
  🔍 = framing difference ("Western media focuses on X, regional media on Y")
  👥 = specific group affected and how
  ⚡ = important detail buried or underreported
  ⚖️ = competing claims or disputed narrative
  ⚠️ = single-source claim / unverified
  🔮 = likely next development

Respond with JSON:
{{"summary": "...", "key_facts": [{{"marker": "emoji", "text": "..."}}]}}""",

        "layer2": """You are writing a world news analysis — the reader should understand this story better than anyone who only reads one outlet.

Structure (1000-1500 words):

## What Actually Happened
Strip away editorial framing. State confirmed facts — who did what, when, where. Use specifics.

## How It's Being Covered
Compare how different outlets and regions frame this story:
- How Western media (Reuters, BBC, CNN) frames it
- How regional/local media frames it
- How the involved governments' own media frames it
- What's emphasized, what's minimized, what's omitted in each

What do these framing differences tell us? Who benefits from each narrative?

## Who's Really Affected
Don't say "the people" — name specific groups:
- Who loses: jobs, safety, rights, access, money
- Who gains: power, territory, contracts, leverage
- The groups no one's talking about but should be
Include numbers and concrete impacts where possible.

## The Bigger Picture
What this story connects to that headlines miss:
- Historical context (has this happened before? what resulted?)
- Economic undercurrents driving the situation
- Power dynamics that explain the actions
- What would change if the average reader understood this

## What to Watch
Specific upcoming events, decisions, deadlines. What would signal escalation vs resolution.

Write like a sharp analyst briefing someone who needs to actually understand this, not just know it happened. No empty transitions. Every sentence should earn its place.""",
    },
}

# Default for categories without specific prompts
DEFAULT_PROMPTS = {
    "focus": "key facts, insights, practical implications",
    "layer1": """Summarize this content in 3-5 sentences, then list 5-8 key points with relevant emoji markers.
Focus on: what happened, why it matters, and what the reader should take away.""",
    "layer2": """Write a detailed article (800-1200 words) covering:
## Summary — what this is about.
## Key Details — the important specifics.
## Analysis — why it matters and implications.
## Takeaways — what the reader should know or do.
Write clearly and concisely. Every paragraph should add value.""",
}


# ═══════════════════════════════════════════════════════════════
# SINGLE ITEM SUMMARIZATION
# ═══════════════════════════════════════════════════════════════

async def summarize_item(title: str, content_text: str, category: str,
                         word_count: int) -> SynthesisResult:
    """Generate two-layer summary for a single item, with formatting guide and fact-checking."""
    from xtesync.services.editorial import get_format_instructions, fact_check, apply_fact_check

    prompts = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPTS)
    format_guide = get_format_instructions(category)

    # Layer 1: Brief + key points
    layer1_prompt = f"""{prompts['layer1']}

---
Title: {title}
Category: {category}
Content ({word_count} words):
{content_text[:10000]}
---

Respond with JSON:
{{
    "summary": "Your 3-5 sentence summary here",
    "key_facts": [
        {{"marker": "emoji", "text": "key point"}}
    ]
}}"""

    # Layer 2: Deep read with formatting instructions
    layer2_prompt = f"""{prompts['layer2']}

{format_guide}

---
Title: {title}
Category: {category}
Content ({word_count} words):
{content_text[:12000]}
---

Follow the formatting guide strictly. Write the full article directly — no JSON, just the article with markdown headers."""

    brief = ""
    key_facts = []
    full_text = ""

    # Generate Layer 1
    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=layer1_prompt)
        text = _extract_json(resp.text)
        data = json.loads(text)
        brief = data.get("summary", "")
        key_facts = data.get("key_facts", [])
    except Exception as e:
        logger.warning("Layer 1 synthesis failed: %s", e)
        brief = content_text[:400]

    # Generate Layer 2
    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=layer2_prompt)
        full_text = resp.text
    except Exception as e:
        logger.warning("Layer 2 synthesis failed: %s", e)
        full_text = content_text

    # Fact-check agent (best-effort, runs on the synthesis)
    if full_text and full_text != content_text:
        try:
            fc_result = await fact_check(full_text, [content_text[:4000]], category)
            full_text = apply_fact_check(full_text, fc_result)
            # Merge any confidence flags into key_facts
            for flag in fc_result.get("confidence_flags", [])[:3]:
                icon = {"confirmed": "✅", "single_source": "⚠️",
                        "unverified": "❓", "developing": "🔄"}.get(flag.get("confidence"), "")
                if icon:
                    key_facts.append({"marker": icon, "text": flag.get("claim", "")})
        except Exception as e:
            logger.warning("Fact-check failed (skipping): %s", e)

    return SynthesisResult(brief=brief, full_text=full_text, key_facts=key_facts)


# ═══════════════════════════════════════════════════════════════
# MULTI-SOURCE CLUSTERING
# ═══════════════════════════════════════════════════════════════

async def cluster_stories(items: list[dict]) -> list[dict]:
    """Group related items into story clusters."""
    if not items:
        return []
    if len(items) == 1:
        return [{
            "headline": items[0].get("title", "Untitled"),
            "category": items[0].get("category") or items[0].get("auto_category") or "general",
            "item_ids": [items[0]["id"]],
        }]

    item_descriptions = []
    for item in items:
        cat = item.get("category") or item.get("auto_category") or "general"
        desc = f"ID:{item['id']} | Category:{cat} | Title: {item.get('title', 'Untitled')}"
        if item.get("summary"):
            desc += f" | Summary: {item['summary'][:150]}"
        item_descriptions.append(desc)

    items_text = "\n".join(item_descriptions)

    client = _get_client()

    if len(items) > 20:
        return await _cluster_large_batch(items, client)

    response = client.models.generate_content(
        model=MODEL,
        contents=f"""Group these items into topic clusters. Items about the same topic/event should be grouped.

ITEMS:
{items_text}

Rules:
- Group items covering the SAME topic (e.g. multiple reviewers covering the same product)
- Keep different categories separate
- Single-source topics are their own cluster
- Write a clear headline for each cluster

Respond with JSON array:
[
    {{
        "headline": "Clear headline for this topic",
        "category": "ai|tech|economics|politics|crypto|science|podcasts|general",
        "item_ids": [1, 2, 3]
    }}
]""",
    )

    try:
        text = _extract_json(response.text)
        clusters = json.loads(text)
        valid_ids = {item["id"] for item in items}
        for cluster in clusters:
            cluster["item_ids"] = [id for id in cluster["item_ids"] if id in valid_ids]
        return [c for c in clusters if c["item_ids"]]
    except (json.JSONDecodeError, IndexError):
        return [{
            "headline": item.get("title", "Untitled"),
            "category": item.get("category") or item.get("auto_category") or "general",
            "item_ids": [item["id"]],
        } for item in items]


async def _cluster_large_batch(items: list[dict], client: genai.Client) -> list[dict]:
    chunk_size = 20
    all_clusters = []
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        chunk_clusters = await cluster_stories(chunk)
        all_clusters.extend(chunk_clusters)
    return all_clusters


# ═══════════════════════════════════════════════════════════════
# MULTI-SOURCE SYNTHESIS (the main briefing output)
# ═══════════════════════════════════════════════════════════════

async def synthesize_cluster(cluster_items: list[dict]) -> SynthesisResult:
    """Synthesize multiple sources about the same topic into a two-layer briefing entry."""
    category = (cluster_items[0].get("category")
                or cluster_items[0].get("auto_category") or "general")
    prompts = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPTS)

    if len(cluster_items) == 1:
        item = cluster_items[0]
        # For single source, use existing summary/detail if available
        return SynthesisResult(
            brief=item.get("summary", ""),
            full_text=item.get("detail", item.get("content_text", "")),
            key_facts=item.get("key_facts") if isinstance(item.get("key_facts"), list)
                      else [{"marker": "❓", "text": "Single source"}],
            source_agreement="Single source — not cross-referenced",
        )

    # Build sources text
    sources_parts = []
    for i, item in enumerate(cluster_items, 1):
        source = item.get("source_domain", "Unknown")
        title = item.get("title", "Untitled")
        content = item.get("content_text", item.get("summary", ""))
        sources_parts.append(
            f"--- SOURCE {i}: {source} ---\n"
            f"Title: {title}\n"
            f"Content:\n{content[:4000]}\n"
        )
    sources_text = "\n".join(sources_parts)

    # Layer 1: Cross-source brief
    layer1_prompt = f"""You have {len(cluster_items)} sources covering the same topic in the "{category}" category.

{prompts['layer1']}

SOURCES:
{sources_text}

IMPORTANT: Combine unique information from ALL sources. Flag where sources agree or disagree.

Respond with JSON:
{{
    "summary": "Your cross-source summary",
    "key_facts": [
        {{"marker": "emoji", "text": "key point"}},
        {{"marker": "⚠️", "text": "where sources disagree — Source A says X, Source B says Y"}}
    ],
    "source_agreement": "Brief: do sources agree? Key differences?"
}}"""

    # Layer 2: Deep synthesis with formatting guide
    from xtesync.services.editorial import get_format_instructions, fact_check, apply_fact_check
    format_guide = get_format_instructions(category)

    layer2_prompt = f"""You have {len(cluster_items)} sources covering the same topic in the "{category}" category.

{prompts['layer2']}

{format_guide}

SOURCES:
{sources_text}

IMPORTANT: Synthesize across all sources. Where they agree, state it confidently. Where they disagree, present both sides.
Include specific details, quotes, and data from each source. Credit sources where relevant.
Follow the formatting guide strictly — proper headers, bold/italic usage, number formatting.
Aim for 1000-1500 words — a solid 3-5 minute read.

Write the article directly with markdown headers."""

    brief = ""
    key_facts = []
    source_agreement = ""
    full_text = ""

    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=layer1_prompt)
        text = _extract_json(resp.text)
        data = json.loads(text)
        brief = data.get("summary", "")
        key_facts = data.get("key_facts", [])
        source_agreement = data.get("source_agreement", "")
    except Exception as e:
        logger.warning("Cluster Layer 1 failed: %s", e)
        brief = " | ".join(i.get("summary", "")[:200] for i in cluster_items)

    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=layer2_prompt)
        full_text = resp.text
    except Exception as e:
        logger.warning("Cluster Layer 2 failed: %s", e)
        full_text = "\n\n---\n\n".join(
            f"From {i.get('source_domain', '?')}: {i.get('detail', i.get('content_text', ''))}"
            for i in cluster_items
        )

    # Fact-check agent on multi-source synthesis
    if full_text and len(cluster_items) > 0:
        try:
            source_texts = [
                i.get("content_text", i.get("summary", ""))
                for i in cluster_items
            ]
            fc_result = await fact_check(full_text, source_texts, category)
            full_text = apply_fact_check(full_text, fc_result)
            for flag in fc_result.get("confidence_flags", [])[:3]:
                icon = {"confirmed": "✅", "single_source": "⚠️",
                        "unverified": "❓", "developing": "🔄"}.get(flag.get("confidence"), "")
                if icon:
                    key_facts.append({"marker": icon, "text": flag.get("claim", "")})
        except Exception as e:
            logger.warning("Cluster fact-check failed (skipping): %s", e)

    return SynthesisResult(
        brief=brief, full_text=full_text,
        key_facts=key_facts, source_agreement=source_agreement,
    )


# ═══════════════════════════════════════════════════════════════

def _extract_json(text: str) -> str:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith(("{", "[")):
                return cleaned
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
    return text
