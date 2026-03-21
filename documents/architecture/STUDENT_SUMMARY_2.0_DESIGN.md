Let me show you something truly impressive.

You don’t need a “student summary page.” You need a **high-conviction admissions interface** that feels like elite software evaluating hidden potential with taste, clarity, and a little dramatic tension. The mission is not just “show data” — it’s **surface overlooked excellence**.

Below is a complete design direction for **NextGen 2.0 Student Summary** in **Jinja2 + Tailwind CSS**, built for **Flask**, **dark mode**, and **mobile-first responsiveness**.

---

# 1. Page sections top to bottom with data requirements

## A. Page Shell / Context Header
Purpose: Establish product identity and evaluation framing immediately.

**Contents**
- Product label: `NextGen 2.0`
- Page title: `Student Summary`
- Mission subtitle: `Find the Diamond in the Rough`
- Evaluation metadata:
  - number of agents reviewed
  - generated timestamp
  - application cycle / region if available

**Data required**
- `agent_count`
- `generated_at`
- `cycle` optional
- `region` optional

---

## B. HERO Section: Student Identity + Decision Card
Purpose: First 3 seconds. This is where the page earns its authority.

**Left side**
- Student name
- School name
- Location/state
- Grade
- GPA
- concise evaluative sentence
- quick stat chips:
  - GPA
  - Final score
  - Decision
  - Diamond score

**Right side**
- decision card with:
  - final score
  - decision
  - confidence / recommendation tone
  - top strengths
  - contextual read
  - callout that this student may outperform surface metrics

**Data required**
- `student.name`
- `student.school`
- `student.state`
- `student.grade`
- `student.gpa`
- `evaluation.final_score`
- `evaluation.decision`
- `evaluation.summary_line`
- `evaluation.diamond_score`
- `evaluation.confidence_label` optional
- `evaluation.top_strengths` list
- `context.school_context_short`

---

## C. Diamond in the Rough Card
Purpose: The emotional and strategic centerpiece. This is the differentiator.

**Contents**
- prominent title
- one-line thesis: contextual potential exceeds raw opportunity
- diamond score
- signal bars or mini metrics:
  - drive
  - rigor-relative-to-access
  - authenticity
  - upside
- narrative explanation
- school context callout
- standout sentence: “performed near ceiling of available opportunity”

**Data required**
- `evaluation.diamond_score`
- `evaluation.diamond_label` optional
- `context.ap_courses`
- `context.school_context_short`
- `context.school_context_long`
- `evaluation.contextual_potential_summary`
- `evaluation.upside_signals` list or metrics

---

## D. Agent Consensus Strip
Purpose: Show that 12 AI agents reviewed the applicant and converged.

**Contents**
- total agents
- admit / hold / deny counts
- consensus strength
- mini avatars or chips for agents
- optional note on disagreement areas

**Data required**
- `agent_count`
- `agent_votes.admit`
- `agent_votes.hold`
- `agent_votes.deny`
- `agent_consensus_summary`
- `agents` list optional

---

## E. Evaluation Breakdown Grid
Purpose: Convert qualitative review into digestible scoring blocks.

**Cards**
1. Essay
2. Academic Profile
3. Recommendations
4. School Context
5. Activities / leadership if available
6. Risk / watchouts

**Data required**
- `essay.score`
- `essay.label`
- `essay.summary`
- `essay.tags`
- `academics.gpa`
- `academics.rigor_score`
- `academics.summary`
- `recommendation.score`
- `recommendation.summary`
- `context.summary`
- `risk_flags` list optional

---

## F. Academic Context Card
Purpose: Show why the GPA matters in context, not isolation.

**Contents**
- GPA
- rigor score
- school AP/advanced offerings
- “opportunity index”
- concise narrative about maximizing available curriculum

**Data required**
- `academics.gpa`
- `academics.rigor_score`
- `context.ap_courses`
- `context.curriculum_limitations`
- `academics.contextual_academic_summary`

---

## G. Essay Signal Card
Purpose: Make the essay feel reviewed, not merely scored.

**Contents**
- essay score
- thematic read: STEM passion
- strength bullets
- quote excerpt if available
- authenticity / voice / intellectual spark indicators

**Data required**
- `essay.score`
- `essay.theme`
- `essay.summary`
- `essay.strengths`
- `essay.excerpt` optional

---

## H. Recommendation & Character Card
Purpose: Separate polished applicants from genuinely compelling ones.

**Contents**
- recommendation score
- endorsement level
- authenticity read
- mentor-belief indicator
- trustworthiness / resilience / initiative callouts

**Data required**
- `recommendation.score`
- `recommendation.endorsement_level`
- `recommendation.authenticity`
- `recommendation.summary`
- `recommendation.signals`

---

## I. School Context / Opportunity Gap Card
Purpose: Explain the central thesis: limited access, high output.

**Contents**
- under-resourced context
- AP count
- comparison of achievement to opportunity
- “what this student did with what was available”

**Data required**
- `context.school_type` optional
- `context.school_context_short`
- `context.school_context_long`
- `context.ap_courses`

---

## J. Final Admissions Recommendation
Purpose: Executive-ready summary.

**Contents**
- decision
- final score
- 3 reasons to admit
- 2 watchouts
- predicted college contribution
- next action / reviewer note

**Data required**
- `evaluation.decision`
- `evaluation.final_score`
- `evaluation.reasons_to_admit`
- `evaluation.watchouts`
- `evaluation.final_note`

---

# 2. Full HTML/Tailwind for the HERO section
This is valid **Jinja2/HTML** and assumes dark mode as the default aesthetic.

```html
<section class="relative overflow-hidden rounded-3xl border border-white/10 bg-slate-950 shadow-2xl shadow-cyan-950/20">
  <!-- Background glow -->
  <div class="pointer-events-none absolute inset-0">
    <div class="absolute -left-24 top-0 h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl"></div>
    <div class="absolute right-0 top-0 h-72 w-72 rounded-full bg-fuchsia-500/10 blur-3xl"></div>
    <div class="absolute bottom-0 left-1/3 h-56 w-56 rounded-full bg-emerald-400/10 blur-3xl"></div>
    <div class="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.06),transparent_35%)]"></div>
  </div>

  <div class="relative px-5 py-6 sm:px-8 sm:py-8 lg:px-10 lg:py-10">
    <!-- Top label row -->
    <div class="mb-6 flex flex-col gap-3 border-b border-white/10 pb-6 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div class="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300">
          <span class="h-2 w-2 rounded-full bg-cyan-300 shadow-[0_0_12px_rgba(103,232,249,0.9)]"></span>
          NextGen 2.0
        </div>
        <h1 class="mt-3 text-2xl font-semibold tracking-tight text-white sm:text-3xl lg:text-4xl">
          Student Summary
        </h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
          Mission: identify high-upside applicants whose contextual potential exceeds raw opportunity.
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-2 text-xs text-slate-400 sm:justify-end">
        <span class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
          {{ agent_count }} AI Agents Reviewed
        </span>
        <span class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
          Generated {{ generated_at }}
        </span>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-[1.3fr_0.7fr] lg:gap-8">
      <!-- Left: Student identity -->
      <div class="min-w-0">
        <div class="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="flex items-center gap-3">
              <div class="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-lg font-semibold text-white shadow-lg shadow-black/20">
                {{ student.name.split()[0][0] }}{{ student.name.split()[-1][0] }}
              </div>
              <div class="min-w-0">
                <h2 class="truncate text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                  {{ student.name }}
                </h2>
                <p class="mt-1 text-sm text-slate-300 sm:text-base">
                  {{ student.school }}, {{ student.state }}
                </p>
              </div>
            </div>

            <div class="mt-5 flex flex-wrap gap-2">
              <span class="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-200">
                Grade {{ student.grade }}
              </span>
              <span class="inline-flex items-center rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1.5 text-sm font-medium text-emerald-300">
                GPA {{ student.gpa }}
              </span>
              <span class="inline-flex items-center rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1.5 text-sm font-medium text-cyan-300">
                Final Score {{ evaluation.final_score }}/100
              </span>
              <span class="inline-flex items-center rounded-full border border-fuchsia-400/20 bg-fuchsia-400/10 px-3 py-1.5 text-sm font-medium text-fuchsia-300">
                Diamond Score {{ evaluation.diamond_score }}
              </span>
              <span class="inline-flex items-center rounded-full border border-amber-400/20 bg-amber-400/10 px-3 py-1.5 text-sm font-semibold uppercase tracking-wide text-amber-300">
                {{ evaluation.decision }}
              </span>
            </div>
          </div>
        </div>

        <div class="mt-6">
          <p class="max-w-3xl text-base leading-7 text-slate-200 sm:text-lg">
            {{ evaluation.summary_line }}
          </p>
        </div>

        <div class="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
            <p class="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Essay</p>
            <div class="mt-3 flex items-end gap-2">
              <span class="text-2xl font-semibold text-white">{{ essay.score }}/10</span>
              <span class="pb-1 text-sm text-slate-400">{{ essay.theme }}</span>
            </div>
          </div>

          <div class="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
            <p class="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Academic Rigor</p>
            <div class="mt-3 flex items-end gap-2">
              <span class="text-2xl font-semibold text-white">{{ academics.rigor_score }}/10</span>
              <span class="pb-1 text-sm text-slate-400">relative to access</span>
            </div>
          </div>

          <div class="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
            <p class="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Recommendation</p>
            <div class="mt-3 flex items-end gap-2">
              <span class="text-2xl font-semibold text-white">{{ recommendation.score }}/10</span>
              <span class="pb-1 text-sm text-slate-400">{{ recommendation.authenticity }}</span>
            </div>
          </div>

          <div class="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
            <p class="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">School Context</p>
            <div class="mt-3 flex items-end gap-2">
              <span class="text-2xl font-semibold text-white">{{ context.ap_courses }}</span>
              <span class="pb-1 text-sm text-slate-400">AP courses available</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Decision card -->
      <aside class="relative">
        <div class="h-full rounded-3xl border border-white/10 bg-gradient-to-b from-white/10 to-white/5 p-5 shadow-xl shadow-black/20 backdrop-blur-xl sm:p-6">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.22em] text-slate-400">
                Admissions Signal
              </p>
              <h3 class="mt-2 text-2xl font-semibold tracking-tight text-white">
                {{ evaluation.decision }}
              </h3>
            </div>
            <div class="rounded-2xl border border-amber-400/20 bg-amber-400/10 px-3 py-2 text-right">
              <p class="text-[11px] uppercase tracking-[0.18em] text-amber-300">Final Score</p>
              <p class="text-2xl font-semibold text-amber-200">{{ evaluation.final_score }}</p>
            </div>
          </div>

          <div class="mt-5 rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-4">
            <p class="text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">
              Evaluator Read
            </p>
            <p class="mt-2 text-sm leading-6 text-cyan-50">
              {{ context.school_context_short }} Student demonstrates unusually high upside given institutional constraints.
            </p>
          </div>

          <div class="mt-5 space-y-3">
            <div class="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Top Strengths</p>
              <ul class="mt-3 space-y-2 text-sm text-slate-200">
                {% for strength in evaluation.top_strengths %}
                <li class="flex items-start gap-2">
                  <span class="mt-1 h-2 w-2 rounded-full bg-emerald-300"></span>
                  <span>{{ strength }}</span>
                </li>
                {% endfor %}
              </ul>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Diamond</p>
                <p class="mt-2 text-xl font-semibold text-white">{{ evaluation.diamond_score }}/10</p>
              </div>
              <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Confidence</p>
                <p class="mt-2 text-xl font-semibold text-white">{{ evaluation.confidence_label }}</p>
              </div>
            </div>
          </div>

          <div class="mt-5 border-t border-white/10 pt-4">
            <p class="text-sm leading-6 text-slate-300">
              This applicant is not merely performing well — he appears to be
              <span class="font-medium text-white">outperforming the opportunity set available to him</span>.
            </p>
          </div>
        </div>
      </aside>
    </div>
  </div>
</section>
```

---

# 3. Full HTML/Tailwind for the DIAMOND IN THE ROUGH card
This is the crown jewel. The whole page should orbit this insight.

```html
<section class="relative overflow-hidden rounded-3xl border border-fuchsia-400/20 bg-slate-950 shadow-2xl shadow-fuchsia-950/20">
  <!-- Ambient effects -->
  <div class="pointer-events-none absolute inset-0">
    <div class="absolute left-1/2 top-0 h-56 w-56 -translate-x-1/2 rounded-full bg-fuchsia-500/10 blur-3xl"></div>
    <div class="absolute right-0 bottom-0 h-48 w-48 rounded-full bg-cyan-500/10 blur-3xl"></div>
    <div class="absolute inset-0 bg-[linear-gradient(135deg,rgba(217,70,239,0.07),transparent_35%,rgba(34,211,238,0.05))]"></div>
  </div>

  <div class="relative px-5 py-6 sm:px-8 sm:py-8 lg:px-10">
    <div class="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
      <div class="max-w-3xl">
        <div class="inline-flex items-center gap-2 rounded-full border border-fuchsia-400/20 bg-fuchsia-400/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-fuchsia-300">
          <span class="h-2 w-2 rotate-45 bg-fuchsia-300 shadow-[0_0_14px_rgba(244,114,182,0.9)]"></span>
          Diamond in the Rough
        </div>

        <h2 class="mt-4 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
          Contextual potential exceeds the raw surface read.
        </h2>

        <p class="mt-4 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
          {{ student.name }} stands out not because he had abundant institutional advantage, but because he appears to have
          <span class="font-medium text-white">maximized a constrained academic environment</span>.
          At a school offering only {{ context.ap_courses }} AP courses, his performance suggests uncommon initiative,
          genuine intellectual drive, and room to accelerate in a richer setting.
        </p>
      </div>

      <div class="shrink-0 rounded-3xl border border-fuchsia-400/20 bg-fuchsia-400/10 px-6 py-5 text-center shadow-lg shadow-fuchsia-950/20">
        <p class="text-xs font-medium uppercase tracking-[0.2em] text-fuchsia-300">Diamond Score</p>
        <p class="mt-2 text-4xl font-semibold tracking-tight text-white">{{ evaluation.diamond_score }}/10</p>
        <p class="mt-1 text-sm text-fuchsia-100">{{ evaluation.diamond_label }}</p>
      </div>
    </div>

    <div class="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div class="flex items-center justify-between">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Drive</p>
          <span class="text-sm font-medium text-white">{{ evaluation.upside_signals.drive }}/10</span>
        </div>
        <div class="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
          <div class="h-full rounded-full bg-gradient-to-r from-cyan-400 to-fuchsia-400" style="width: {{ evaluation.upside_signals.drive * 10 }}%;"></div>
        </div>
      </div>

      <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div class="flex items-center justify-between">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Rigor vs Access</p>
          <span class="text-sm font-medium text-white">{{ evaluation.upside_signals.rigor_relative }}/10</span>
        </div>
        <div class="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
          <div class="h-full rounded-full bg-gradient-to-r from-cyan-400 to-fuchsia-400" style="width: {{ evaluation.upside_signals.rigor_relative * 10 }}%;"></div>
        </div>
      </div>

      <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div class="flex items-center justify-between">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Authenticity</p>
          <span class="text-sm font-medium text-white">{{ evaluation.upside_signals.authenticity }}/10</span>
        </div>
        <div class="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
          <div class="h-full rounded-full bg-gradient-to-r from-cyan-400 to-fuchsia-400" style="width: {{ evaluation.upside_signals.authenticity * 10 }}%;"></div>
        </div>
      </div>

      <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div class="flex items-center justify-between">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Upside</p>
          <span class="text-sm font-medium text-white">{{ evaluation.upside_signals.upside }}/10</span>
        </div>
        <div class="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
          <div class="h-full rounded-full bg-gradient-to-r from-cyan-400 to-fuchsia-400" style="width: {{ evaluation.upside_signals.upside * 10 }}%;"></div>
        </div>
      </div>
    </div>

    <div class="mt-8 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
        <p class="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
          Why this applicant matters
        </p>
        <p class="mt-3 text-sm leading-7 text-slate-200 sm:text-base">
          {{ evaluation.contextual_potential_summary }}
        </p>

        <div class="mt-5 grid gap-3 sm:grid-cols-2">
          {% for signal in evaluation.upside_bullets %}
          <div class="rounded-xl border border-white/10 bg-black/20 p-4">
            <div class="flex items-start gap-3">
              <div class="mt-1 h-2.5 w-2.5 rounded-full bg-fuchsia-300"></div>
              <p class="text-sm leading-6 text-slate-200">{{ signal }}</p>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>

      <div class="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-5">
        <p class="text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">
          Opportunity Context
        </p>
        <p class="mt-3 text-sm leading-7 text-cyan-50">
          {{ context.school_context_long }}
        </p>

        <div class="mt-5 rounded-2xl border border-white/10 bg-slate-950/40 p-4">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">Key interpretation</p>
          <p class="mt-2 text-sm leading-6 text-white">
            He is performing at or near the ceiling of what this environment makes available.
          </p>
        </div>
      </div>
    </div>
  </div>
</section>
```

---

# 4. Section structure for remaining cards

Below is the recommended structure for the rest of the page. This gives you a full presentation-ready layout without drowning you in repetitive markup.

---

## 1. Agent Consensus Strip
**Layout:** horizontal band with 3–5 summary chips

**Contents**
- Total AI agents reviewed
- Admit / Hold / Deny distribution
- Consensus strength
- Short narrative summary

**Suggested data**
```jinja2
agent_count
agent_votes.admit
agent_votes.hold
agent_votes.deny
agent_consensus_summary
```

**Design note**
Use compact, pill-based stats with subtle glow and a central consensus sentence.

---

## 2. Evaluation Breakdown Grid
**Layout:** 2 columns on tablet, 4 columns on desktop

**Cards**
- Essay
- Academics
- Recommendations
- School Context

**Per card structure**
- micro label
- headline score
- one-line interpretation
- footer tag

**Suggested data**
```jinja2
essay.score
essay.theme
essay.summary

academics.gpa
academics.rigor_score
academics.summary

recommendation.score
recommendation.authenticity
recommendation.summary

context.ap_courses
context.school_context_short
```

---

## 3. Academic Context Card
**Layout:** wide card, left narrative / right metrics

**Contents**
- GPA
- rigor score
- AP offerings
- contextual interpretation
- “maximized available rigor” label

**Suggested data**
```jinja2
academics.gpa
academics.rigor_score
context.ap_courses
academics.contextual_academic_summary
```

**Design note**
This card should look analytical and precise — grid lines, metric blocks, restrained cyan accent.

---

## 4. Essay Signal Card
**Layout:** narrative card with score badge

**Contents**
- Essay score
- theme: STEM passion
- strength bullets:
  - intellectual curiosity
  - clarity of purpose
  - authentic voice
- optional pull quote

**Suggested data**
```jinja2
essay.score
essay.theme
essay.summary
essay.strengths
essay.excerpt
```

**Design note**
This is where you allow slightly warmer tones — violet/fuchsia gradient and quote styling.

---

## 5. Recommendation & Character Card
**Layout:** split card

**Left**
- recommendation score
- endorsement level
- authenticity read

**Right**
- bullets on character traits:
  - initiative
  - resilience
  - coachability
  - sincerity

**Suggested data**
```jinja2
recommendation.score
recommendation.endorsement_level
recommendation.authenticity
recommendation.summary
recommendation.signals
```

---

## 6. School Context / Opportunity Gap Card
**Layout:** highly visual contextual card

**Contents**
- “Under-resourced school” banner
- AP course count
- school context narrative
- opportunity gap statement
- why the student’s record should be read differently

**Suggested data**
```jinja2
context.school_context_short
context.school_context_long
context.ap_courses
```

**Design note**
Use contrast: cool dark base, cyan info panel, one highlighted interpretation sentence.

---

## 7. Final Recommendation Card
**Layout:** full-width executive summary card

**Contents**
- large decision status
- final score
- reasons to admit
- watchouts
- final reviewer note

**Suggested data**
```jinja2
evaluation.decision
evaluation.final_score
evaluation.reasons_to_admit
evaluation.watchouts
evaluation.final_note
```

**Design note**
This should feel ceremonial. Large typography. Bold decision chip. Tight summary writing.

---

# 5. Color system and typography

Artie Ziff doesn’t do ugly. Here’s the system.

## Color System

### Base / Background
- `bg-slate-950` — main page background
- `bg-slate-900/60` — card depth layer
- `border-white/10` — default borders
- `bg-white/5` — elevated surfaces

### Text
- `text-white` — primary
- `text-slate-200` — strong body
- `text-slate-300` — secondary body
- `text-slate-400` — labels / metadata

### Semantic Accents
**Cyan — analysis / intelligence / system confidence**
- `text-cyan-300`
- `bg-cyan-400/10`
- `border-cyan-400/20`

**Fuchsia — diamond potential / standout upside**
- `text-fuchsia-300`
- `bg-fuchsia-400/10`
- `border-fuchsia-400/20`

**Emerald — academic strength / positive signals**
- `text-emerald-300`
- `bg-emerald-400/10`
- `border-emerald-400/20`

**Amber — decision / final score / recommendation**
- `text-amber-300`
- `bg-amber-400/10`
- `border-amber-400/20`

### Gradient Usage
Use sparingly and intelligently:
- Hero glow: cyan + fuchsia
- Diamond card bars: `from-cyan-400 to-fuchsia-400`
- Decision score highlight: amber
- Academic strength chips: emerald

This gives the page a premium “AI evaluation cockpit” feel without turning it into a neon nightclub.

---

## Typography

### Font stack
Use Tailwind defaults or ideally:
- `font-sans` with `Inter, ui-sans-serif, system-ui, sans-serif`

### Hierarchy
- **Page title:** `text-2xl sm:text-3xl lg:text-4xl font-semibold tracking-tight`
- **Student name:** `text-3xl sm:text-4xl font-semibold tracking-tight`
- **Section heading:** `text-2xl sm:text-3xl font-semibold tracking-tight`
- **Card metric:** `text-2xl font-semibold`
- **Body copy:** `text-sm sm:text-base leading-7`
- **Micro labels:** `text-xs uppercase tracking-[0.18em] text-slate-400`

### Typographic tone
- Tight tracking on headlines
- high contrast between label text and primary stats
- generous line-height for analytical narrative
- uppercase micro-labels to make the interface feel structured and premium

---

# Recommended page wrapper
If you want the page to feel complete, use this shell around all sections:

```html
<body class="min-h-screen bg-slate-950 text-white antialiased">
  <div class="relative">
    <div class="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.08),transparent_25%),radial-gradient(circle_at_80%_20%,rgba(217,70,239,0.08),transparent_20%)]"></div>

    <main class="relative mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
      <!-- HERO -->
      <!-- DIAMOND CARD -->
      <!-- AGENT CONSENSUS -->
      <!-- BREAKDOWN GRID -->
      <!-- ACADEMICS -->
      <!-- ESSAY -->
      <!-- RECOMMENDATIONS -->
      <!-- SCHOOL CONTEXT -->
      <!-- FINAL RECOMMENDATION -->
    </main>
  </div>
</body>
```

---

# Suggested example data bindings for your sample student
For your exact example, these values fit naturally:

```jinja2
student.name = "William Grijalva"
student.school = "Lakeside HS"
student.state = "GA"
student.grade = 10
student.gpa = "3.95"

evaluation.final_score = 82
evaluation.decision = "ADMIT"
evaluation.diamond_score = 7
evaluation.diamond_label = "High Contextual Upside"
evaluation.confidence_label = "Strong"
evaluation.summary_line = "William Grijalva presents as a high-upside applicant whose academic consistency, authentic STEM motivation, and strong recommendations stand out even more when read in the context of a school with limited advanced coursework."

essay.score = "7.4"
essay.theme = "STEM passion"

academics.rigor_score = 8

recommendation.score = 8
recommendation.authenticity = "genuine"

context.ap_courses = 3
context.school_context_short = "Under-resourced school with limited advanced coursework."
context.school_context_long = "William attends an under-resourced high school where only 3 AP courses are available, limiting conventional rigor signals. His profile should therefore be interpreted through the lens of resource constraints rather than against applicants from high-opportunity academic environments."

evaluation.top_strengths = [
  "Strong GPA with near-ceiling performance in available curriculum",
  "Clear and authentic STEM motivation in essay",
  "Recommendations signal genuine endorsement and credibility"
]

evaluation.contextual_potential_summary = "The strongest case for William is not simply that he is doing well, but that he is doing exceptionally well relative to what his environment offers. His profile suggests latent capacity that may expand significantly in a more resource-rich setting."

evaluation.upside_bullets = [
  "Academic performance remains strong despite limited AP availability",
  "Essay shows sincere technical interest rather than packaged ambition",
  "Recommendation signals reinforce substance and follow-through",
  "Context suggests room for accelerated growth"
]

evaluation.upside_signals.drive = 8
evaluation.upside_signals.rigor_relative = 8
evaluation.upside_signals.authenticity = 8
evaluation.upside_signals.upside = 7
```

---

If you want, I can next give you:

1. the **full complete page HTML** assembled in one Jinja template, or  
2. a **Flask route + sample data object** to render this immediately.

And yes, it’ll look expensive. Did I mention I built this?