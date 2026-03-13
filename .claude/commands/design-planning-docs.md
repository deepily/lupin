---
description: Create maintainable design & planning documentation structure
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Glob, Grep
arguments:
  - name: mode
    description: Operation mode (create|reorganize|analyze)
    required: false
    default: create
  - name: project-name
    description: Short project identifier (e.g., jwt-oauth, websocket-refactor)
    required: false
---

# Design & Planning Documentation Generator

## Purpose

This command helps you create and maintain well-structured design and planning documentation that remains readable, maintainable, and within Claude Code's 25,000 token limit. It implements a **meta-pattern system** that provides five battle-tested documentation structures, each optimized for different project types.

### What is a Meta-Pattern?

A meta-pattern is a template-of-templates: a reusable documentation structure that can be customized for your specific project. Instead of starting from scratch each time, you select a proven pattern and adapt it to your needs. Think of it like architectural blueprints - you don't redesign plumbing from scratch for each house; you use proven patterns and customize them.

### Benefits

- **Maintainable**: Documents stay organized as projects evolve
- **Scalable**: Token budget planning prevents document bloat
- **Discoverable**: Clear cross-references and navigation
- **Reusable**: Proven patterns adapted to your project
- **Archival**: Completed phases archived automatically

---

## Phase 0: Introduction & Mode Selection

### Command Modes

This slash command supports three operational modes:

#### Mode 1: Create (Default)
- **Purpose**: Start a new design/planning documentation structure from scratch
- **Use when**: Beginning a new project or initiative
- **Process**: Interview → Pattern Selection → Structure Generation → Template Population
- **Output**: Complete directory structure with templated documents

#### Mode 2: Reorganize
- **Purpose**: Transform existing documentation into maintainable structure
- **Use when**: Documentation has grown unwieldy or unstructured
- **Process**: Content Analysis → Pattern Selection → Content Migration → Validation
- **Output**: Reorganized structure with content preserved and archived

#### Mode 3: Analyze
- **Purpose**: Assess current documentation health and recommend improvements
- **Use when**: Evaluating whether reorganization is needed
- **Process**: Structure Analysis → Token Counting → Pattern Matching → Recommendations
- **Output**: Health report with actionable recommendations

### What to Expect

This command will guide you through a structured process:

1. **Discovery Interview** (2-3 minutes): Answer questions about your project
2. **Pattern Recommendation** (1 minute): Review and approve suggested structure
3. **Token Budget Planning** (1 minute): Understand capacity constraints
4. **Structure Generation** (2-5 minutes): Automated file/directory creation
5. **Content Organization** (if reorganizing): Content migration and validation
6. **Validation & Completion** (1 minute): Verification and reporting

**Total time**: 7-15 minutes depending on mode and complexity

---

## Phase 1: Discovery Interview

Before recommending a documentation pattern, I need to understand your project. Please answer the following questions (you can skip questions that aren't relevant):

### Project Identification

1. **What is the project name or identifier?**
   - Example: "jwt-oauth-authentication", "websocket-refactor", "payment-integration"
   - This becomes your document prefix (e.g., `2025.09.30-jwt-oauth-implementation.md`)

2. **What is the project scale?**
   - Small: 1-2 weeks, single developer
   - Medium: 2-8 weeks, 1-3 developers
   - Large: 2+ months, multiple developers/stakeholders

3. **What is your preferred short identifier?**
   - Used in filenames and cross-references
   - Examples: "jwt-oauth", "ws-refactor", "payment-v2"
   - Keep it under 20 characters, use hyphens

### Current State Assessment

4. **Are you starting fresh or reorganizing existing documentation?**
   - Fresh: No existing documentation
   - Reorganizing: Have documentation that needs restructuring
   - Hybrid: Some documentation exists but incomplete

5. **If reorganizing, where is your existing documentation?**
   - Provide file path(s) to current document(s)
   - Example: `/path/to/src/rnd/2025.09.15-websocket-design.md`

### Structure & Timeline

6. **Does your project have distinct phases/milestones?**
   - Yes, I can identify 3+ clear phases
   - Maybe, I have some phases in mind
   - No, it's more exploratory/research-oriented
   - Not sure yet

7. **What is your project time horizon?**
   - Sprint: 1-2 weeks
   - Short-term: 2-4 weeks
   - Medium-term: 1-3 months
   - Long-term: 3+ months

8. **What is your expected completion target?**
   - Firm deadline: [DATE]
   - Flexible target: [TIMEFRAME]
   - No specific deadline
   - Exploratory/ongoing

### Content Nature

9. **What is the primary focus of your documentation?**
   - Implementation planning (building something new)
   - Research & analysis (exploring options/approaches)
   - Feature specification (defining requirements)
   - Troubleshooting investigation (solving problems)
   - Architecture design (system structure/patterns)
   - Hybrid: [DESCRIBE COMBINATION]

10. **How much technical depth do you need?**
    - High: Code examples, API specs, data models
    - Medium: Component descriptions, flow diagrams
    - Low: High-level concepts and decisions
    - Variable: Some sections deep, others high-level

11. **Do you need to track decision-making?**
    - Yes, need comprehensive decision log
    - Yes, but only for major decisions
    - No, just document final choices
    - Not sure

### Audience & Usage

12. **Who is the primary audience?**
    - Just me (personal reference)
    - Team members (collaboration)
    - Stakeholders (status reporting)
    - Future maintainers (knowledge transfer)
    - Mixed audience

13. **How frequently will you update this documentation?**
    - Daily (active development)
    - Weekly (regular sprints)
    - Milestone-based (phase completions)
    - Ad-hoc (as needed)

14. **Does this integrate with other documentation?**
    - Yes, part of larger documentation ecosystem
    - Yes, references other specific documents
    - No, standalone documentation
    - Not sure yet

### Research Component

15. **Does this project involve research/exploration?**
    - Yes, significant research component
    - Yes, some initial research needed
    - No, implementation-focused
    - Already completed separately

16. **If research involved, where is it located?**
    - Mixed into planning documents (needs separation)
    - Separate research documents exist: [PATHS]
    - Not yet created
    - N/A

17. **What is the research scope/size?**
    - Small: 1-2 documents, < 5k tokens
    - Medium: 3-5 documents, 5-15k tokens
    - Large: 6+ documents, > 15k tokens
    - N/A

18. **Is research completed or ongoing?**
    - Completed (ready to archive/reference)
    - Ongoing (active investigation)
    - Not started
    - N/A

19. **What are the key research outputs?**
    - Technology comparisons/evaluations
    - Proof-of-concept implementations
    - Literature review/documentation analysis
    - Experimental results/benchmarks
    - Architecture explorations
    - N/A

---

## Phase 2: Pattern Recommendation Engine

Based on your answers, I'll recommend one of five base documentation patterns. Each pattern is optimized for specific project types and has been proven in real-world projects.

### Pattern Library

#### Pattern A: Large Implementation Project

**Best for**: Multi-phase implementation projects with clear milestones

**Characteristics**:
- Multiple distinct implementation phases
- 2+ months duration
- Requires detailed planning and tracking
- Clear separation between active and completed work

**Structure**:
```
{project-name}/
├── 00-index.md                          # Master index and navigation
├── 01-implementation-current.md         # Active phases only
├── 02-architecture.md                   # System design and patterns
├── 03-decisions.md                      # Decision log
├── 04-testing-validation.md             # QA and validation plans
├── archive/
│   ├── phases-01-03-completed.md        # Completed early phases
│   └── phases-04-06-completed.md        # Completed later phases
└── research/                            # Optional research component
    ├── 00-research-index.md
    ├── technology-evaluation.md
    └── proof-of-concept-results.md
```

**Token Budget**:
- 00-index.md: 500-1,000 tokens (navigation hub)
- 01-implementation-current.md: 8,000-12,000 tokens (active phases)
- 02-architecture.md: 4,000-8,000 tokens (stable reference)
- 03-decisions.md: 2,000-5,000 tokens (cumulative log)
- 04-testing-validation.md: 3,000-6,000 tokens (test plans)
- Archive files: 10,000-15,000 tokens each (completed work)
- Research files: 3,000-8,000 tokens each (if present)

**Real-world example**: JWT/OAuth Authentication Implementation (Dec 2024 - Feb 2025)

---

#### Pattern B: Research & Analysis Document

**Best for**: Exploratory projects focused on investigation and analysis

**Characteristics**:
- Research-heavy, implementation-light
- Multiple technologies/approaches to evaluate
- Emphasis on findings and recommendations
- May lead to future implementation project

**Structure**:
```
{project-name}/
├── 00-index.md                          # Research overview
├── 01-objectives-scope.md               # Research goals and boundaries
├── 02-technology-evaluation.md          # Option comparisons
├── 03-findings-recommendations.md       # Results and next steps
├── 04-proof-of-concept/                 # Experimental work
│   ├── experiment-01.md
│   └── experiment-02.md
└── references/                          # External resources
    └── documentation-links.md
```

**Token Budget**:
- 00-index.md: 500-1,000 tokens
- 01-objectives-scope.md: 2,000-4,000 tokens
- 02-technology-evaluation.md: 5,000-10,000 tokens
- 03-findings-recommendations.md: 4,000-8,000 tokens
- Experiment files: 2,000-5,000 tokens each
- References: 1,000-3,000 tokens

**Real-world example**: WebSocket Architecture Research (Jun 2025)

---

#### Pattern C: Feature Specification

**Best for**: Well-defined features requiring detailed specification

**Characteristics**:
- Clear feature boundaries
- Detailed requirements and acceptance criteria
- User stories and use cases
- Integration specifications

**Structure**:
```
{project-name}/
├── 00-index.md                          # Feature overview
├── 01-requirements.md                   # Functional and non-functional requirements
├── 02-user-stories.md                   # Use cases and scenarios
├── 03-technical-design.md               # Implementation approach
├── 04-api-specifications.md             # Interface definitions
├── 05-testing-criteria.md               # Acceptance tests
└── 06-implementation-notes.md           # Development journal
```

**Token Budget**:
- 00-index.md: 500-1,000 tokens
- 01-requirements.md: 3,000-6,000 tokens
- 02-user-stories.md: 2,000-5,000 tokens
- 03-technical-design.md: 4,000-8,000 tokens
- 04-api-specifications.md: 3,000-7,000 tokens
- 05-testing-criteria.md: 2,000-4,000 tokens
- 06-implementation-notes.md: 3,000-8,000 tokens

**Use when**: Adding well-scoped feature to existing system

---

#### Pattern D: Troubleshooting Investigation

**Best for**: Debugging complex issues requiring systematic investigation

**Characteristics**:
- Problem-focused (not feature-focused)
- Hypothesis testing and experimentation
- Detailed observations and findings
- Solution validation

**Structure**:
```
{project-name}/
├── 00-index.md                          # Investigation overview
├── 01-problem-statement.md              # Issue description and impact
├── 02-investigation-log.md              # Timeline of investigation activities
├── 03-hypotheses-tests.md               # Theories and validation attempts
├── 04-findings.md                       # Root causes and insights
├── 05-solution.md                       # Implemented fix and validation
└── 06-prevention.md                     # Future mitigation strategies
```

**Token Budget**:
- 00-index.md: 500-1,000 tokens
- 01-problem-statement.md: 2,000-4,000 tokens
- 02-investigation-log.md: 4,000-8,000 tokens
- 03-hypotheses-tests.md: 3,000-6,000 tokens
- 04-findings.md: 2,000-5,000 tokens
- 05-solution.md: 3,000-6,000 tokens
- 06-prevention.md: 2,000-4,000 tokens

**Use when**: Diagnosing and fixing complex system issues

---

#### Pattern E: Architecture Design Document

**Best for**: System-level architecture and design decisions

**Characteristics**:
- High-level system design
- Component relationships and interactions
- Design principles and patterns
- Long-term reference document

**Structure**:
```
{project-name}/
├── 00-index.md                          # Architecture overview
├── 01-system-context.md                 # Business context and constraints
├── 02-architecture-overview.md          # High-level system design
├── 03-component-design.md               # Detailed component specifications
├── 04-data-models.md                    # Data structures and schemas
├── 05-integration-patterns.md           # Inter-component communication
├── 06-security-considerations.md        # Security design
├── 07-scalability-performance.md        # Non-functional design
└── 08-decision-rationale.md             # ADRs (Architecture Decision Records)
```

**Token Budget**:
- 00-index.md: 500-1,000 tokens
- 01-system-context.md: 2,000-4,000 tokens
- 02-architecture-overview.md: 4,000-7,000 tokens
- 03-component-design.md: 5,000-10,000 tokens
- 04-data-models.md: 3,000-6,000 tokens
- 05-integration-patterns.md: 3,000-6,000 tokens
- 06-security-considerations.md: 2,000-5,000 tokens
- 07-scalability-performance.md: 2,000-5,000 tokens
- 08-decision-rationale.md: 2,000-5,000 tokens

**Use when**: Designing new systems or major refactoring

---

### Research Integration Options

All patterns can include a research component. When you answer "yes" to research questions in Phase 1, I'll offer three integration approaches:

#### Option 1: Integrate Research (Recommended for small-medium research)
- Add `research/` directory to chosen pattern
- Research files coexist with planning documents
- Total token budget includes research allocation
- Best when: Research < 10k tokens, tightly coupled to project

#### Option 2: Create Separate Research Structure (Recommended for large research)
- Research gets its own directory parallel to planning structure
- Research has dedicated index and organization
- Independent token budget management
- Best when: Research > 10k tokens, reusable across projects

#### Option 3: Skip Research Integration
- Research stays in current location or doesn't need formal structure
- Planning documents reference research via links
- Best when: Research completed or managed elsewhere

---

### Pattern Recommendation Process

After you answer the Phase 1 questions, I will:

1. **Analyze your responses** to identify project characteristics
2. **Score each pattern** based on fit with your answers
3. **Present top recommendation** with explanation
4. **Show runner-up patterns** for comparison
5. **Ask for your approval or preference**

**Example recommendation output**:

```
Based on your answers, I recommend:

PRIMARY RECOMMENDATION: Pattern A (Large Implementation Project)

Reasoning:
- You indicated 8+ weeks duration (matches Pattern A timeline)
- Multiple phases identified: Phase 1-8 (matches Pattern A structure)
- Implementation-focused with architecture component (Pattern A strength)
- Need for completed phase archival (Pattern A feature)

ALTERNATIVE PATTERNS:
- Pattern C (Feature Specification): Consider if scope is smaller than indicated
- Pattern E (Architecture Design): Consider if design phase should be separate

Do you approve Pattern A, or would you prefer a different pattern?
```

**Your options**:
1. Approve recommended pattern → Continue to Phase 3
2. Select alternative pattern → Explain why, then continue
3. Request hybrid pattern → Describe combination needed
4. Ask questions → Clarify pattern differences

---

## Phase 3: Token Budget Planning

### Why Token Budgets Matter

Claude Code has a **25,000 token context window limit**. When documentation exceeds this limit:

- Claude cannot read entire document at session start
- Context is lost across conversation turns
- Navigation becomes difficult
- Maintenance burden increases

**Token budget planning prevents these problems** by:
1. Setting size targets for each document
2. Triggering archival before limits hit
3. Maintaining readable, scannable documents
4. Enabling efficient Claude Code usage

### Token Counting Basics

**Rough estimates** (for planning purposes):
- 1 token ≈ 4 characters
- 100 tokens ≈ 75 words
- 1,000 tokens ≈ 750 words or 3-4 paragraphs
- 5,000 tokens ≈ 3,750 words or 3-4 pages
- 10,000 tokens ≈ 7,500 words or 8-10 pages
- 25,000 tokens ≈ 18,750 words or 25 pages

**Real-world examples** from JWT/OAuth reorganization:

| Document | Tokens | Content Type |
|----------|--------|--------------|
| `2025.06.03-jwt-oauth-implementation.md` (original) | 23,847 | All phases mixed together |
| `01-implementation-current.md` (after split) | 8,456 | Active phases 4-8 only |
| `02-architecture.md` (after split) | 6,234 | System design and patterns |
| `archive/phases-01-03-completed.md` | 12,789 | Completed phases archived |
| `00-index.md` | 892 | Navigation and cross-refs |

**Key insight**: Original 23,847-token document was approaching limit. After reorganization, no single document exceeds 13k tokens, leaving comfortable margin.

### Token Budget Allocation

Based on your chosen pattern, here's your recommended token budget:

**[I will populate this section after pattern selection in Phase 2]**

Example for Pattern A (Large Implementation Project):

| Document | Target Range | Warning Threshold | Action at Threshold |
|----------|--------------|-------------------|---------------------|
| 00-index.md | 500-1,000 | 1,500 | Simplify, move detail to other docs |
| 01-implementation-current.md | 8,000-12,000 | 15,000 | Archive completed phases |
| 02-architecture.md | 4,000-8,000 | 10,000 | Split into architecture + patterns docs |
| 03-decisions.md | 2,000-5,000 | 7,000 | Archive old decisions |
| 04-testing-validation.md | 3,000-6,000 | 8,000 | Archive completed test results |
| Archive files | 10,000-15,000 | 20,000 | Further subdivide if needed |

**Total project budget**: 60,000-100,000 tokens (distributed across multiple files)

### Budget Monitoring

I will help you monitor token budgets by:

1. **Initial setup**: Calculate baseline token counts after structure creation
2. **Periodic checks**: Count tokens when you update documentation
3. **Threshold warnings**: Alert you when approaching warning thresholds
4. **Archival triggers**: Recommend archival when thresholds hit

**Command for manual token counting**:
```bash
wc -w /path/to/document.md | awk '{print int($1 * 1.33)}'
```
(Multiplies word count by 1.33 to estimate tokens)

### Budget Planning Example

Let's walk through how JWT/OAuth project managed tokens:

**Initial state** (June 2025):
- Single document: `2025.06.03-jwt-oauth-implementation.md`
- Token count: 23,847
- Status: Approaching 25k limit, reorganization needed

**Reorganization analysis**:
- Phases 1-3: Completed (12,789 tokens) → Archive
- Phases 4-8: Active (8,456 tokens) → Keep in current
- Architecture: Stable reference (6,234 tokens) → Separate doc
- Decisions: Cumulative log (2,104 tokens) → Separate doc
- Index: Navigation (892 tokens) → New doc

**Result after reorganization**:
- Largest document: 12,789 tokens (archive file)
- Active document: 8,456 tokens (50% headroom before warning)
- Total project: ~30,000 tokens across 5 files
- Status: Healthy, maintainable, room to grow

### Your Budget Plan

After you approve your pattern in Phase 2, I will:

1. Show your specific token budget table
2. Explain warning thresholds for each document
3. Describe archival triggers and strategies
4. Set up monitoring approach

**Approval checkpoint**: Do you understand the token budget approach and agree to the proposed allocations?

---

## Phase 4: Structure Generation

Once you approve the pattern and token budget, I'll create your documentation structure automatically.

### What I'll Create

Based on your chosen pattern, I will:

1. **Create directory structure** using `mkdir` commands
2. **Generate all template files** using `Write` tool
3. **Customize templates** with your project information
4. **Populate placeholders** with context from Phase 1 answers
5. **Establish cross-references** between documents
6. **Create README** in parent directory (if needed)

### Template Customization

All templates contain placeholders that I'll replace with your actual project details:

**Standard placeholders**:
- `{PROJECT_NAME}`: Your full project name
- `{PROJECT_ID}`: Your short identifier
- `{DATE}`: Creation date (YYYY.MM.DD format)
- `{PATTERN}`: Selected pattern (A, B, C, D, or E)
- `{DURATION}`: Project duration estimate
- `{PHASES}`: Number of phases (if applicable)

**Example transformation**:

Template content:
```markdown
# {PROJECT_NAME} Implementation

Project ID: {PROJECT_ID}
Created: {DATE}
Pattern: {PATTERN}
Duration: {DURATION}
```

After customization:
```markdown
# JWT/OAuth Authentication Implementation

Project ID: jwt-oauth
Created: 2025.06.03
Pattern: Pattern A (Large Implementation Project)
Duration: 8-12 weeks
```

### Structure Generation Process

I'll use TodoWrite to track creation of each file:

```
[LUPIN] Creating directory structure for {PROJECT_ID}
[LUPIN] Creating 00-index.md
[LUPIN] Creating 01-implementation-current.md
[LUPIN] Creating 02-architecture.md
[LUPIN] Creating 03-decisions.md
[LUPIN] Creating 04-testing-validation.md
[LUPIN] Creating archive/ directory
[LUPIN] Creating research/ directory (if applicable)
[LUPIN] Validating all files created successfully
[LUPIN] Verifying cross-references work
```

### Example: Pattern A Structure Generation

**Commands I'll execute**:

```bash
# Create main directory
mkdir -p /path/to/src/rnd/{PROJECT_ID}

# Create subdirectories
mkdir -p /path/to/src/rnd/{PROJECT_ID}/archive
mkdir -p /path/to/src/rnd/{PROJECT_ID}/research  # if research component

# Note: Files created using Write tool (not shown here)
```

**Files created**:

1. **00-index.md**: Master navigation hub
   - Links to all other documents
   - Quick reference section
   - Status indicators for each phase
   - Recent updates log

2. **01-implementation-current.md**: Active implementation phases
   - Current phase details
   - Next phase planning
   - Blockers and dependencies
   - Progress tracking

3. **02-architecture.md**: System design
   - Architecture diagrams
   - Component descriptions
   - Design patterns used
   - Technology stack

4. **03-decisions.md**: Decision log
   - Decision format: Context, Options, Choice, Rationale
   - Chronological order
   - Tagged by category
   - Reversal tracking

5. **04-testing-validation.md**: QA and validation
   - Test strategies
   - Test case lists
   - Validation criteria
   - Test results log

6. **archive/** directory: Completed phases
   - Created empty initially
   - Populated as phases complete
   - Naming: `phases-XX-YY-completed.md`

7. **research/** directory: Research materials (optional)
   - 00-research-index.md
   - Individual research documents
   - Proof-of-concept results
   - Technology evaluations

### Cross-Reference Setup

Each document includes navigation sections linking to related documents:

**Example cross-reference section** (in 01-implementation-current.md):
```markdown
## Related Documentation

- **[Index](00-index.md)**: Master navigation and project overview
- **[Architecture](02-architecture.md)**: System design and patterns
- **[Decisions](03-decisions.md)**: Decision log and rationale
- **[Testing](04-testing-validation.md)**: QA and validation plans
- **[Completed Phases](archive/)**: Archived implementation phases
- **[Research](research/00-research-index.md)**: Research and explorations
```

These links work in:
- GitHub/GitLab web interface
- VSCode markdown preview
- Most markdown editors
- Claude Code's Read tool

### Template Source

Templates are located in:
```
/path/to/src/rnd/2025.09.27-prompts/templates/design-planning/
├── pattern-a/
│   ├── 00-index.template.md
│   ├── 01-implementation-current.template.md
│   ├── 02-architecture.template.md
│   ├── 03-decisions.template.md
│   └── 04-testing-validation.template.md
├── pattern-b/
├── pattern-c/
├── pattern-d/
└── pattern-e/
```

I'll read the appropriate templates for your chosen pattern and customize them.

### Progress Notifications

I'll send notifications at these milestones:

1. **Structure creation started**: `notify-claude-async "[LUPIN] Starting structure generation for {PROJECT_ID}" --type=progress --priority=medium`

2. **Directory creation complete**: After `mkdir` commands succeed

3. **Halfway point**: After creating ~50% of files

4. **Structure creation complete**: `notify-claude-async "[LUPIN] Structure generation complete for {PROJECT_ID} - {N} files created" --type=progress --priority=medium`

5. **Validation complete**: After verifying all files and cross-references

### Validation Checklist

After creation, I'll verify:

- [ ] All directories exist
- [ ] All template files created successfully
- [ ] All placeholders replaced with actual values
- [ ] Cross-reference links point to existing files
- [ ] Token counts within initial budgets
- [ ] No duplicate or conflicting content
- [ ] README updated (if applicable)
- [ ] Git status shows new files

### What You'll Do Next

After structure generation:

1. **Review the index file** (`00-index.md`) to understand navigation
2. **Start populating content** in active documents
3. **Update as you work** through your project
4. **Archive completed phases** when done
5. **Monitor token budgets** periodically

I'll provide specific guidance on how to use each document type in your chosen pattern.

---

## Phase 5: Content Organization (Reorganize Mode)

**This phase only applies if you're running in `reorganize` mode.** Skip to Phase 6 if you're in `create` mode.

### Reorganization Goals

When reorganizing existing documentation, our goals are:

1. **Preserve all content**: Nothing gets lost in the process
2. **Improve discoverability**: Clear structure and navigation
3. **Reduce token bloat**: Active docs stay under budget
4. **Enable maintenance**: Easy to update going forward
5. **Archive completed work**: Historical reference without clutter

### Reorganization Process

#### Step 1: Content Discovery

First, I'll read and analyze your existing documentation:

```bash
# You'll provide path(s) in Phase 1, I'll read them
Read /path/to/existing/document.md
```

I'll analyze:
- Total token count
- Logical sections and structure
- Active vs. completed content
- Architecture/design sections
- Decision records
- Research content
- Timestamp patterns

**Example analysis output**:
```
Document Analysis: 2025.06.03-jwt-oauth-implementation.md

Total tokens: 23,847 (approaching 25k limit)

Content breakdown:
- Header and index: 892 tokens
- Phase 1 (Completed): 4,234 tokens
- Phase 2 (Completed): 3,987 tokens
- Phase 3 (Completed): 4,568 tokens
- Phase 4 (Active): 2,109 tokens
- Phase 5 (Active): 2,345 tokens
- Phase 6 (Planning): 1,876 tokens
- Phase 7 (Planning): 1,567 tokens
- Phase 8 (Planning): 1,003 tokens
- Architecture section: 6,234 tokens (stable)
- Decision log: 2,104 tokens (cumulative)

Recommendations:
- Archive Phases 1-3 (completed): 12,789 tokens
- Keep Phases 4-8 (active/planned): 8,900 tokens
- Extract architecture to separate doc: 6,234 tokens
- Extract decisions to separate doc: 2,104 tokens
- Create index: ~800 tokens estimated
```

#### Step 2: Content Extraction Strategy

Based on analysis, I'll propose an extraction strategy:

**For Pattern A (Large Implementation Project)**, typical strategy:
1. **Completed phases** → `archive/phases-XX-YY-completed.md`
2. **Active phases** → `01-implementation-current.md`
3. **Architecture content** → `02-architecture.md`
4. **Decision records** → `03-decisions.md`
5. **Testing/validation** → `04-testing-validation.md`
6. **Navigation hub** → `00-index.md`

**Approval checkpoint**: I'll show you the extraction plan and ask for approval before proceeding.

#### Step 3: Content Extraction

I'll systematically extract content section by section:

**Example extraction** (Phases 1-3 to archive):

```markdown
Original location: 2025.06.03-jwt-oauth-implementation.md, lines 150-650

Destination: archive/phases-01-03-completed.md

Content:
- Phase 1: JWT Token Generation (Completed 2024.12.15)
- Phase 2: Token Validation Middleware (Completed 2024.12.22)
- Phase 3: OAuth Integration (Completed 2025.01.10)

Tokens: 12,789
Cross-references added:
- Link back to index
- Forward links to architecture decisions
- Status indicators (COMPLETED)
```

I'll use `Read` to extract content and `Write` to create new files, ensuring exact content preservation.

#### Step 4: Active Content Migration

Active/current content moves to working documents:

**Example migration** (Phases 4-8 to current implementation):

```markdown
Original location: 2025.06.03-jwt-oauth-implementation.md, lines 650-1200

Destination: 01-implementation-current.md

Content:
- Phase 4: Refresh Token Implementation (IN PROGRESS)
- Phase 5: Session Management (PLANNED)
- Phase 6: Security Hardening (PLANNED)
- Phase 7: Configuration & Middleware (PLANNED)
- Phase 8: Testing & Documentation (PLANNED)

Tokens: 8,900
Cross-references added:
- Link back to index
- Links to completed phases in archive
- Links to architecture and decisions
```

#### Step 5: Stable Content Extraction

Architecture, design, and reference content moves to dedicated documents:

**Example: Architecture extraction**

```markdown
Original location: Throughout original doc, sections marked "Architecture"

Destination: 02-architecture.md

Content:
- System architecture diagram
- Authentication flow
- Token lifecycle
- Security model
- Database schema
- API endpoints

Tokens: 6,234
Cross-references added:
- Link back to index
- Links to relevant phases
- Links to architecture decisions in 03-decisions.md
```

**Example: Decision log extraction**

```markdown
Original location: Throughout original doc, sections marked "Decision"

Destination: 03-decisions.md

Content:
- D001: JWT vs. Session-based auth
- D002: HS256 vs. RS256 algorithm choice
- D003: Refresh token rotation strategy
- D004: Token storage location (httpOnly cookies)
- D005: OAuth provider selection

Tokens: 2,104
Format: Standardized decision template for each entry
Cross-references: Link to relevant phases and architecture sections
```

#### Step 6: Original Document Archival

After successful extraction, I'll archive the original document:

```bash
# Create archive-original directory if needed
mkdir -p /path/to/src/rnd/{PROJECT_ID}/archive-original

# Move original document to archive
mv /path/to/2025.06.03-jwt-oauth-implementation.md \
   /path/to/src/rnd/{PROJECT_ID}/archive-original/2025.06.03-jwt-oauth-implementation-ORIGINAL.md
```

**Archival includes**:
- Rename with `-ORIGINAL` suffix
- Move to `archive-original/` directory
- Add README explaining archival
- Keep timestamp intact
- Preserve file permissions

**README in archive-original/**:
```markdown
# Original Document Archive

This directory contains the original documentation before reorganization.

Original file: 2025.06.03-jwt-oauth-implementation-ORIGINAL.md
Reorganization date: 2025.09.30
Reason: Token count (23,847) approaching Claude Code limit (25,000)

New structure: See ../00-index.md for navigation

Content preserved in:
- ../01-implementation-current.md (active phases)
- ../02-architecture.md (system design)
- ../03-decisions.md (decision log)
- ../archive/phases-01-03-completed.md (completed phases)

No content was lost during reorganization.
```

#### Step 7: Validation

After reorganization, I'll validate content preservation:

**Validation checklist**:
- [ ] All original sections accounted for in new structure
- [ ] Token counts add up correctly (original ≈ sum of new docs)
- [ ] Cross-references all valid (no broken links)
- [ ] Timestamps preserved accurately
- [ ] Status indicators correct (completed vs. active)
- [ ] No duplicate content across documents
- [ ] Original document safely archived
- [ ] Navigation paths clear from index

**Validation report example**:

```
Reorganization Validation Report

Original document:
- File: 2025.06.03-jwt-oauth-implementation.md
- Tokens: 23,847

New structure:
- 00-index.md: 892 tokens
- 01-implementation-current.md: 8,900 tokens
- 02-architecture.md: 6,234 tokens
- 03-decisions.md: 2,104 tokens
- archive/phases-01-03-completed.md: 12,789 tokens
- Total: 31,919 tokens

Token difference: +8,072 tokens (expected due to added navigation, cross-references, and formatting)

Content verification:
✓ All 8 phases accounted for
✓ Architecture section preserved
✓ All 5 decision records present
✓ Timestamps intact
✓ Cross-references valid

Status: PASSED - Reorganization successful
```

#### Step 8: Git Status Check

I'll show you what changed:

```bash
git status
```

Expected output:
```
On branch wip-documentation-reorganization

New files:
  src/rnd/2025.09.29-jwt-oauth/00-index.md
  src/rnd/2025.09.29-jwt-oauth/01-implementation-current.md
  src/rnd/2025.09.29-jwt-oauth/02-architecture.md
  src/rnd/2025.09.29-jwt-oauth/03-decisions.md
  src/rnd/2025.09.29-jwt-oauth/04-testing-validation.md
  src/rnd/2025.09.29-jwt-oauth/archive/phases-01-03-completed.md
  src/rnd/2025.09.29-jwt-oauth/archive-original/README.md

Modified files:
  (none expected)

Renamed/moved:
  src/rnd/2025.06.03-jwt-oauth-implementation.md →
  src/rnd/2025.09.29-jwt-oauth/archive-original/2025.06.03-jwt-oauth-implementation-ORIGINAL.md
```

### Reorganization Completion

After validation passes, I'll:

1. **Send completion notification**:
   ```bash
   notify-claude-async "[LUPIN] Documentation reorganization complete: {PROJECT_ID} - {N} files created, {X} tokens redistributed" --type=progress --priority=medium
   ```

2. **Provide navigation guide**: Show you how to use the new structure

3. **Suggest next steps**: How to maintain the structure going forward

---

## Phase 6: Validation & Completion

This is the final phase for both `create` and `reorganize` modes.

### Final Validation Checklist

I'll systematically verify the entire structure:

#### File System Validation

```bash
# Verify all directories exist
ls -la /path/to/src/rnd/{PROJECT_ID}/

# Expected output shows all directories
```

- [ ] Main project directory exists
- [ ] `archive/` subdirectory exists (Pattern A, D, E)
- [ ] `research/` subdirectory exists (if research component)
- [ ] `archive-original/` exists (reorganize mode only)
- [ ] All expected files present

#### File Content Validation

- [ ] All template placeholders replaced
- [ ] No `{PLACEHOLDER}` strings remain
- [ ] Dates in correct format (YYYY.MM.DD)
- [ ] Project name consistent across files
- [ ] Cross-references use correct paths

#### Cross-Reference Validation

I'll test each cross-reference link:

```bash
# For each link in format [text](path.md), verify path exists
# Example verification
test -f /path/to/src/rnd/{PROJECT_ID}/02-architecture.md && echo "✓ Link valid" || echo "✗ Link broken"
```

- [ ] Index links to all main documents
- [ ] Main documents link back to index
- [ ] Archive links work bidirectionally
- [ ] Research links work (if applicable)
- [ ] External references clearly marked

#### Token Budget Validation

I'll count tokens for each created document:

```bash
# Count tokens (word count * 1.33 approximation)
for file in /path/to/src/rnd/{PROJECT_ID}/*.md; do
  tokens=$(wc -w "$file" | awk '{print int($1 * 1.33)}')
  echo "$(basename $file): $tokens tokens"
done
```

**Expected output example**:
```
00-index.md: 876 tokens (target: 500-1000) ✓
01-implementation-current.md: 3,245 tokens (target: 8000-12000) ✓
02-architecture.md: 4,123 tokens (target: 4000-8000) ✓
03-decisions.md: 1,567 tokens (target: 2000-5000) ✓
04-testing-validation.md: 2,098 tokens (target: 3000-6000) ✓
```

- [ ] All documents within target ranges
- [ ] No documents exceeding warning thresholds
- [ ] Total project tokens calculated
- [ ] Comfortable headroom for growth

#### Content Quality Validation (Reorganize Mode)

If reorganizing:
- [ ] No content lost from original
- [ ] No duplicate content across documents
- [ ] Logical content grouping
- [ ] Clear section boundaries
- [ ] Timestamps preserved

### Git Status Check

I'll show final git status:

```bash
git status
```

**For create mode**, expect:
```
Untracked files:
  src/rnd/{PROJECT_ID}/00-index.md
  src/rnd/{PROJECT_ID}/01-implementation-current.md
  src/rnd/{PROJECT_ID}/02-architecture.md
  ... (all newly created files)
```

**For reorganize mode**, expect:
```
New files:
  src/rnd/{PROJECT_ID}/ (directory and contents)

Renamed:
  src/rnd/original-doc.md → src/rnd/{PROJECT_ID}/archive-original/original-doc-ORIGINAL.md
```

**I will NOT commit these changes automatically.** You'll commit when ready.

### History.md Update

I'll update the main history.md file with a session entry:

```markdown
## 2025.09.30 - Session 1: Design Documentation Structure Created

### Created: {PROJECT_ID} Documentation Structure

**Pattern**: Pattern {X} ({Pattern Name})

**Structure**:
- Created {N} documentation files
- Set up token budgets (total: ~{X}k tokens)
- Established cross-reference navigation
- {Mode-specific details}

**Files Created**:
- `src/rnd/{PROJECT_ID}/00-index.md` - Master index
- `src/rnd/{PROJECT_ID}/01-implementation-current.md` - Active phases
- ... (list all files)

**Next Steps**:
- Begin populating content in active documents
- Monitor token budgets as content grows
- Archive completed phases when done

**Status**: Structure complete, ready for content population
```

**Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`

I'll insert this entry at the top of the current month section.

### Completion Report

I'll generate a comprehensive completion report:

```markdown
# Design Documentation Structure - Completion Report

Project: {PROJECT_NAME}
Project ID: {PROJECT_ID}
Pattern: {PATTERN_NAME}
Mode: {create|reorganize|analyze}
Date: {DATE}
Session duration: {X} minutes

## Structure Created

Directory: /path/to/src/rnd/{PROJECT_ID}/

Files created: {N}
Total lines: {X}
Total tokens: {Y} (distributed across {N} files)

## File Inventory

| File | Lines | Tokens | Purpose | Status |
|------|-------|--------|---------|--------|
| 00-index.md | XX | XXX | Master index | Ready |
| 01-implementation-current.md | XX | XXX | Active phases | Ready |
| 02-architecture.md | XX | XXX | System design | Ready |
| ... | ... | ... | ... | ... |

## Token Budget Status

| Document | Current | Target | Warning | Headroom |
|----------|---------|--------|---------|----------|
| 00-index.md | 876 | 500-1000 | 1500 | 624 tokens |
| 01-implementation-current.md | 3245 | 8000-12000 | 15000 | 11755 tokens |
| ... | ... | ... | ... | ... |

Total project capacity: {X} tokens ({Y}% utilized)

## Validation Results

✓ All directories created successfully
✓ All files created successfully
✓ All placeholders replaced
✓ Cross-references validated ({N} links tested)
✓ Token budgets within targets
✓ Git status clean (untracked files as expected)
✓ History.md updated

{For reorganize mode:}
✓ Original document archived safely
✓ All content preserved (validation passed)
✓ {X} phases archived, {Y} phases kept active

## Next Steps

1. **Start populating content** in active documents:
   - Begin with 00-index.md for project overview
   - Then work in 01-implementation-current.md for current phase
   - Reference 02-architecture.md as you design

2. **Maintain token budgets**:
   - Run token counts periodically: `wc -w file.md | awk '{print int($1 * 1.33)}'`
   - Archive completed phases when done
   - Monitor warning thresholds

3. **Use cross-references**:
   - Keep index updated as you add content
   - Link between documents for navigation
   - Update status indicators

4. **Commit when ready**:
   - Review all files first
   - Use descriptive commit message
   - Example: "Add {PROJECT_ID} design documentation structure (Pattern {X})"

## How to Use This Structure

### Starting a new phase:
1. Open 01-implementation-current.md
2. Add phase header with status indicator
3. Fill in phase details (goals, tasks, decisions)
4. Update 00-index.md with phase summary

### Completing a phase:
1. Mark phase as COMPLETED in 01-implementation-current.md
2. Move phase content to archive/phases-XX-completed.md
3. Update 00-index.md status
4. Count tokens in remaining active document

### Making architectural decisions:
1. Open 03-decisions.md
2. Add new decision entry using standard format
3. Link to relevant phases and architecture sections
4. Update 02-architecture.md if design changes

### Adding research:
1. Create new file in research/ directory
2. Update research/00-research-index.md
3. Link from main index and relevant phases

## Support

If you need help:
- Review pattern documentation in this command file
- Check token budgets: `wc -w *.md`
- Validate links: Test in VSCode markdown preview
- Ask questions: Tag me (@claude) with questions

---

Structure generation complete! Ready to begin documentation.
```

### Completion Notification

I'll send final notification:

```bash
notify-claude-async "[LUPIN] Design documentation structure complete: {PROJECT_ID} using Pattern {X} - {N} files created, ready for content" --type=progress --priority=medium
```

### Handoff to User

At this point, I'll hand off to you with:

1. **Completion report** (as above)
2. **Quick start guide** for using the structure
3. **Reminder about token budgets** and monitoring
4. **Offer to answer questions** about the structure

**Example handoff message**:

```
Structure generation complete! 🎉

I've created your {PROJECT_NAME} documentation structure using Pattern {X}.

📁 Location: /path/to/src/rnd/{PROJECT_ID}/

📊 Files created: {N}
📝 Total tokens: {Y} (comfortable headroom for growth)
✓ All validation checks passed

🚀 Ready to start documenting!

Next steps:
1. Open 00-index.md to review the structure
2. Start populating 01-implementation-current.md with your first phase
3. Monitor token budgets as you grow the documentation

Questions? Ask me anything about using the structure!

Note: Changes are not yet committed. Review the files and commit when ready.
```

---

## Command Implementation Notes

### For Claude Code Developers

When implementing this slash command:

1. **Parse arguments**:
   - `mode`: create (default) | reorganize | analyze
   - `project-name`: Optional, will prompt if not provided

2. **Use TodoWrite throughout**:
   - Create initial todo list at start
   - Update after each major phase
   - Mark items complete as you progress
   - Use [LUPIN] prefix for all items

3. **Send notifications at milestones**:
   - Phase completion (medium priority)
   - User approval needed (high priority)
   - Errors or blockers (urgent priority)
   - Final completion (medium priority)

4. **Template locations**:
   ```
   /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/rnd/2025.09.27-prompts/templates/design-planning/
   ```

5. **Error handling**:
   - Check for directory existence before creating
   - Validate file writes succeeded
   - Handle missing templates gracefully
   - Report errors clearly to user

6. **Token counting**:
   - Use `wc -w | awk '{print int($1 * 1.33)}'` for estimates
   - Warn if any document approaches 15k tokens
   - Alert if approaching 20k tokens (critical threshold)

7. **Git integration**:
   - Show git status at completion
   - Do NOT auto-commit
   - Do NOT auto-push
   - Let user review and commit manually

8. **History.md updates**:
   - Read current history.md
   - Find current month section
   - Insert new session entry at top
   - Preserve existing format

### Command Invocation Examples

```bash
# Create new structure (will prompt for project name)
/design-planning-docs

# Create with project name specified
/design-planning-docs --project-name=websocket-refactor

# Reorganize existing documentation
/design-planning-docs --mode=reorganize --project-name=jwt-oauth

# Analyze existing documentation health
/design-planning-docs --mode=analyze --project-name=payment-integration
```

### Phase Execution Order

Always execute phases in order:

1. Phase 0: Introduction (show immediately)
2. Phase 1: Discovery Interview (interactive Q&A)
3. Phase 2: Pattern Recommendation (show patterns, get approval)
4. Phase 3: Token Budget Planning (show budget table, get approval)
5. Phase 4: Structure Generation (create files, customize templates)
6. Phase 5: Content Organization (reorganize mode only)
7. Phase 6: Validation & Completion (validate, report, hand off)

### Approval Checkpoints

Always wait for user approval at these points:

1. After Phase 2: Pattern selection
2. After Phase 3: Token budget plan
3. After Phase 5 Step 2: Extraction strategy (reorganize mode)
4. Before final completion: Review completion report

Never proceed without explicit approval.

### Validation Requirements

Before completion, MUST validate:

- All directories exist
- All files created successfully
- All placeholders replaced
- Cross-references valid
- Token counts within budgets
- Git status clean
- History.md updated

If any validation fails, report error and ask for guidance.

---

## Appendix: Pattern Selection Decision Tree

Use this decision tree to recommend patterns:

```
START
  |
  ├─ Is this primarily research/exploration?
  |    YES → Pattern B (Research & Analysis)
  |    NO → Continue
  |
  ├─ Is this a problem investigation/debugging?
  |    YES → Pattern D (Troubleshooting Investigation)
  |    NO → Continue
  |
  ├─ Is this high-level architecture/system design?
  |    YES → Pattern E (Architecture Design)
  |    NO → Continue
  |
  ├─ Does project have 3+ distinct phases?
  |    YES → Pattern A (Large Implementation)
  |    NO → Pattern C (Feature Specification)
  |
  └─ Does project include research component?
       YES → Offer +Research variant
       NO → Use base pattern
```

## Appendix: Real-World Examples

### Example 1: JWT/OAuth Implementation (Pattern A)

**Context**: Large authentication implementation project spanning 3 months

**Original state**: Single 23,847-token document approaching Claude Code limit

**Reorganization approach**:
- Pattern A selected (Large Implementation Project)
- Phases 1-3 archived (completed work)
- Phases 4-8 kept active (current/future work)
- Architecture extracted to separate doc
- Decisions extracted to separate doc

**Results**:
- Largest document: 12,789 tokens (archive)
- Active document: 8,456 tokens (50% headroom)
- Improved discoverability and maintenance
- Room to grow through remaining phases

**Key insight**: Aggressive archival of completed work kept active document manageable.

---

### Example 2: WebSocket Architecture Research (Pattern B)

**Context**: Research project to evaluate WebSocket architecture approaches

**Requirements**:
- Compare multiple architecture patterns
- Document proof-of-concept implementations
- Make technology recommendations
- Support future implementation project

**Pattern B structure**:
- Objectives and scope clearly defined
- Technology evaluation matrix
- PoC results documented
- Recommendations for next phase

**Results**:
- Clear research outputs
- Easy to reference in later implementation
- Research findings archived for future reference

**Key insight**: Separating research from implementation planning improved both.

---

### Example 3: Payment Integration (Pattern C)

**Context**: Well-scoped feature addition to existing e-commerce system

**Requirements**:
- Clear feature boundaries (payment processing only)
- Detailed API specifications
- Integration with existing order system
- Comprehensive test coverage

**Pattern C structure**:
- Requirements clearly specified
- User stories for all payment scenarios
- Technical design for integration points
- API specifications for payment endpoints
- Acceptance criteria for testing

**Results**:
- Feature delivered on schedule
- Clear requirements prevented scope creep
- Easy stakeholder communication

**Key insight**: Well-defined features benefit from specification-focused pattern.

---

### Example 4: WebSocket Event Routing Bug (Pattern D)

**Context**: Complex bug investigation for event routing issues

**Investigation timeline**: 2 weeks of systematic debugging

**Pattern D structure**:
- Problem statement with examples of failures
- Detailed investigation log (timeline of attempts)
- Hypotheses tested (each with results)
- Root cause findings
- Solution implementation
- Prevention strategies

**Results**:
- Root cause identified and fixed
- Prevention measures implemented
- Investigation process documented for future reference
- Similar issues avoided using lessons learned

**Key insight**: Systematic investigation pattern prevented going in circles.

---

## Appendix: Template Preview

### Pattern A: 00-index.md Template

```markdown
# {PROJECT_NAME} - Master Index

Project ID: `{PROJECT_ID}`
Created: {DATE}
Pattern: Pattern A (Large Implementation Project)
Duration: {DURATION}

## Quick Navigation

- **[Current Implementation](01-implementation-current.md)**: Active phases and planning
- **[Architecture](02-architecture.md)**: System design and patterns
- **[Decisions](03-decisions.md)**: Decision log and rationale
- **[Testing & Validation](04-testing-validation.md)**: QA and test plans
- **[Completed Phases](archive/)**: Archived implementation phases
- **[Research](research/00-research-index.md)**: Research and explorations *(if applicable)*

## Project Overview

{Brief 2-3 paragraph description of project - TO BE FILLED}

## Current Status

**Active Phase**: Phase {X} - {Phase Name}
**Progress**: {X}% complete
**Last Updated**: {DATE}

## Phase Summary

| Phase | Status | Completion Date | Document |
|-------|--------|-----------------|----------|
| Phase 1: {Name} | COMPLETED | {DATE} | [Archive](archive/phases-01-03-completed.md#phase-1) |
| Phase 2: {Name} | COMPLETED | {DATE} | [Archive](archive/phases-01-03-completed.md#phase-2) |
| Phase 3: {Name} | COMPLETED | {DATE} | [Archive](archive/phases-01-03-completed.md#phase-3) |
| Phase 4: {Name} | IN PROGRESS | - | [Current](01-implementation-current.md#phase-4) |
| Phase 5: {Name} | PLANNED | - | [Current](01-implementation-current.md#phase-5) |
| ... | ... | ... | ... |

## Recent Updates

- **{DATE}**: {Brief update description}
- **{DATE}**: {Brief update description}
- **{DATE}**: {Brief update description}

## Key Decisions

- **[D001](03-decisions.md#d001)**: {Brief decision summary}
- **[D002](03-decisions.md#d002)**: {Brief decision summary}
- **[D003](03-decisions.md#d003)**: {Brief decision summary}

## Token Budget Status

| Document | Current | Target | Status |
|----------|---------|--------|--------|
| This index | {X} | 500-1000 | ✓ |
| Current implementation | {X} | 8000-12000 | ✓ |
| Architecture | {X} | 4000-8000 | ✓ |
| Decisions | {X} | 2000-5000 | ✓ |
| Testing | {X} | 3000-6000 | ✓ |

**Total project tokens**: ~{X} across {N} files

---

*Last updated: {DATE} by {AUTHOR}*
```

---

## Appendix: FAQ

### Q: When should I use this command vs. creating docs manually?

**A**: Use this command when:
- Starting a project that will span 2+ weeks
- Documentation will exceed 5,000 tokens
- Multiple phases or milestones involved
- Need to track decisions systematically
- Existing documentation becoming unwieldy

Create manually when:
- One-off task or spike
- Single document sufficient
- Documentation < 3,000 tokens
- Exploratory work without clear structure

### Q: Can I modify the generated structure?

**A**: Yes! The generated structure is a starting point. Feel free to:
- Add additional documents as needed
- Reorganize sections within documents
- Adjust token budgets based on actual usage
- Customize templates for your workflow

The structure provides a foundation, not a straitjacket.

### Q: What if my project doesn't fit any pattern?

**A**: You have options:
1. Choose closest pattern and customize
2. Request hybrid pattern (combine elements)
3. Use Pattern A as default (most flexible)

Most projects fit patterns with minor customization.

### Q: How often should I check token counts?

**A**: Check token counts:
- After major content additions
- Before archiving phases
- Monthly for long-running projects
- When document feels "large"

Use command: `wc -w file.md | awk '{print int($1 * 1.33)}'`

### Q: When should I archive completed phases?

**A**: Archive when:
- Phase marked COMPLETED
- Active document approaching 12-15k tokens
- Content no longer actively referenced
- Focus shifting to new phases

Don't archive too early - wait until phase truly complete.

### Q: Can I use this for non-implementation projects?

**A**: Yes! Patterns support various project types:
- Pattern B: Research projects
- Pattern D: Troubleshooting/debugging
- Pattern E: Architecture/design work
- Pattern C: Feature specifications

Choose pattern matching your project type.

### Q: What if I need to reorganize again later?

**A**: Run command in reorganize mode again:
```bash
/design-planning-docs --mode=reorganize --project-name={PROJECT_ID}
```

The command can reorganize already-organized structures as projects evolve.

### Q: How do I handle documents exceeding token budgets?

**A**: When document exceeds warning threshold:

1. **For implementation docs**: Archive completed phases
2. **For architecture docs**: Split into architecture + patterns
3. **For decision logs**: Archive old decisions
4. **For research docs**: Split into multiple focused documents

Run `/design-planning-docs --mode=analyze` for recommendations.

---

**End of Command Specification**

Total lines: ~1,150
Comprehensive coverage: ✓
Ready for implementation: ✓
