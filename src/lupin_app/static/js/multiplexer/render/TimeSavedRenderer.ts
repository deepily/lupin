/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-4 — the Time Saved dashboard, ported from legacy
// `refreshTimeSavedStats` (notifications.js:8608) and `renderTopSolutions`
// (:8663), with the markup at notifications.html:1276-1306.
//
// Four stat tiles and a leaderboard, fetched ONCE at mount and otherwise only
// when the operator presses 🔄. No timer, and no fetch on expand (T1) — this
// pane is a summary, not a monitor, and a poll would spend two requests a
// minute on numbers that move hourly.
//
// 🔴 THE THREE FAILURE RULES ARE THE POINT OF THIS PANE, AND THEY ALL SAY THE
// SAME THING: A FAILED READ MUST NOT ERASE WHAT IS ON SCREEN.
//   - a non-2xx leaves the previous values in place (T2)
//   - a throw only logs — it never clears the tiles and never paints a message (T5)
//   - the two endpoints are independent: the second failing does not undo the
//     first's repaint, exactly as legacy's two separate `if (response.ok)`
//     blocks behave
// The reason is that this dashboard's numbers are cumulative. "--" here does not
// read as "the fetch failed", it reads as "you have saved no time", which is a
// claim about the operator's work rather than about the network.
//
// ⚠️ BUILT ON `ApiClient`, NOT A BARE `fetch` (T6). Legacy calls `fetch` directly
// with a hand-attached Bearer header, so neither call refreshes an expired
// token and both silently start failing once it lapses. `ApiClient` goes through
// `AuthManager`. This is the one place B-4 deliberately does NOT mirror legacy,
// and the build plan names it as such rather than leaving it to be discovered.

import type { ApiClient } from "../api/ApiClient";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

/** `GET /api/stats/time-saved` — the caller's own totals. */
export interface TimeSavedStats {
  total_time_saved_formatted?     : string;
  time_saved_for_others_formatted?: string;
  solutions_created?              : number;
  total_replays_benefited?        : number;
}

/** One row of the leaderboard. */
export interface TopSolution {
  question?            : string;
  replays?             : number;
  time_saved_formatted?: string;
}

/** `GET /api/stats/time-saved/global` — the cross-user leaderboard. */
export interface GlobalTimeSavedStats {
  top_solutions?: ReadonlyArray<TopSolution>;
}

export const TIME_SAVED_ENDPOINT        = "/api/stats/time-saved";
export const TIME_SAVED_GLOBAL_ENDPOINT = "/api/stats/time-saved/global";

/**
 * What a tile reads before the first fetch resolves (B10).
 *
 * ⚠️ IT IS A PLACEHOLDER, NOT A ZERO, and the difference is the whole reason it
 * is not "0". An unmeasured total and a measured zero are different facts, and
 * only one of them is a statement about the operator's work.
 */
export const TIME_SAVED_PLACEHOLDER = "--";

/** The leaderboard's two pre-row states (B10) — loading, then a measured empty. */
export const TOP_SOLUTIONS_LOADING = "Loading...";
export const TOP_SOLUTIONS_EMPTY   = "No replayed solutions yet";

export interface TimeSavedRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  /** Test helper — run the fetch pair and await both legs. */
  refreshForTesting(): Promise<void>;
}

export interface TimeSavedRendererOptions {
  api  : Pick<ApiClient, "get">;
  /** Test injection — where a failed read is reported. Defaults to the console. */
  logFn?: ( message: string ) => void;
}

interface Tile {
  key     : keyof TimeSavedStats;
  label   : string;
  testid  : string;
  /** Formatted strings fall back to the placeholder; counts fall back to 0 — as legacy. */
  numeric : boolean;
}

/**
 * The four tiles, in legacy's order (notifications.html:1284-1299).
 *
 * 🔴 THE TWO FALLBACKS DIFFER AND THAT IS COPIED DELIBERATELY. Legacy writes
 * `stats.total_time_saved_formatted || '--'` for the two formatted strings and
 * `stats.solutions_created || 0` for the two counts. So a server that omits a
 * duration says "unmeasured" while one that omits a count says "none" — an
 * inconsistency, but a live one, and a pane that quietly harmonised it would
 * disagree with the other client about what the same payload means.
 */
const TILES: ReadonlyArray<Tile> = Object.freeze( [
  { key: "total_time_saved_formatted",      label: "Time Saved (You)",        testid: "multiplexer-time-total",             numeric: false },
  { key: "time_saved_for_others_formatted", label: "Time Saved for Others",   testid: "multiplexer-time-others",            numeric: false },
  { key: "solutions_created",               label: "Solutions Created",       testid: "multiplexer-solutions-created",      numeric: true  },
  { key: "total_replays_benefited",         label: "Cache Hits (You)",        testid: "multiplexer-replays-benefited",      numeric: true  },
] );

class TimeSavedRendererImpl implements TimeSavedRenderer {
  private readonly api   : Pick<ApiClient, "get">;
  private readonly logFn : ( message: string ) => void;

  private root        : HTMLElement | null = null;
  private header      : SectionHeaderHandle | null = null;
  private collapseOff : ( () => void ) | null = null;
  private valueEls    : Map<string, HTMLElement> = new Map();
  private solutionsEl : HTMLElement | null = null;
  private mounted     = false;

  constructor( opts: TimeSavedRendererOptions ) {
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: the console is the runtime sink; tests inject a recorder.
    this.logFn = opts.logFn ?? ( ( m ) => console.warn( m ) );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "TimeSavedRenderer already mounted" );

    // The 🔄 is a <button>, so `headerClickShouldCollapse` already refuses to
    // collapse on its click — this is the structural equivalent of legacy's
    // hand-written `event.stopPropagation()` (notifications.html:1279) and is
    // why there is no stopPropagation call here (B2).
    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "time-saved-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-time-saved-refresh" );
    refreshBtn.setAttribute( "title", "Refresh time-saved statistics" );
    refreshBtn.textContent = "🔄";
    // B8 — refetches BOTH endpoints and repaints. No debounce guard: legacy has
    // none, and adding one here would be a behaviour the other client lacks.
    refreshBtn.addEventListener( "click", () => { void this.refresh(); } );

    const header = renderSectionHeader( {
      icon    : "⏱️",
      title   : "Time Saved Dashboard",
      testid  : "multiplexer-time-saved-header",
      actions : [ refreshBtn ],
    } );
    this.header = header;
    // B7 — a STATIC header. The count chip stays empty: there is no one number
    // this pane counts, and a chip showing one of the four would be picking a
    // favourite. Legacy's header carries no count either.
    header.countEl.setAttribute( "data-testid", "multiplexer-time-saved-count" );

    const body = document.createElement( "div" );
    body.className = "section-content time-saved-body";

    const grid = document.createElement( "div" );
    grid.className = "stats-grid";
    for ( const tile of TILES ) {
      const item = document.createElement( "div" );
      item.className = "stat-item";

      const value = document.createElement( "span" );
      value.className = "stat-value";
      value.setAttribute( "data-testid", tile.testid );
      value.textContent = TIME_SAVED_PLACEHOLDER;

      const label = document.createElement( "span" );
      label.className = "stat-label";
      label.textContent = tile.label;

      item.append( value, label );
      grid.appendChild( item );
      this.valueEls.set( tile.key, value );
    }

    const solutions = document.createElement( "div" );
    solutions.className = "top-solutions";
    const heading = document.createElement( "h4" );
    heading.textContent = "🏆 Most Helpful Solutions";
    this.solutionsEl = document.createElement( "div" );
    this.solutionsEl.className = "top-solutions-list";
    this.solutionsEl.setAttribute( "data-testid", "multiplexer-top-solutions" );
    this.solutionsEl.textContent = TOP_SOLUTIONS_LOADING;
    solutions.append( heading, this.solutionsEl );

    body.append( grid, solutions );
    root.replaceChildren( header.header, body );

    // B3 — NOT persisted. Session-only collapse, which is the default and is
    // stated here because A-2 #6 made persistence available and the absence of
    // a third argument is now a decision rather than the only option.
    this.collapseOff = wireSectionCollapse( root, header );

    this.root    = root;
    this.mounted = true;

    // T1 — fetched ONCE, at init. Not on expand, and not on a timer.
    void this.refresh();
  }

  unmount(): void {
    if ( this.collapseOff !== null ) this.collapseOff();
    this.collapseOff = null;
    this.header      = null;
    this.solutionsEl = null;
    this.valueEls    = new Map();
    if ( this.root !== null ) this.root.replaceChildren();
    this.root    = null;
    this.mounted = false;
  }

  refreshForTesting(): Promise<void> {
    return this.refresh();
  }

  /**
   * Fetch both endpoints and repaint what each one answers.
   *
   * Requires:
   *   - the pane is mounted
   *
   * Ensures:
   *   - the tiles repaint from `/api/stats/time-saved` when it answers
   *   - the leaderboard repaints from `/api/stats/time-saved/global` when it answers
   *   - 🔴 a failure of EITHER leg leaves that half of the pane untouched and
   *     logs; it never clears a tile, never blanks the leaderboard, and never
   *     paints an error into the pane (T2, T5)
   *   - the two legs are independent: the second failing cannot undo the first
   *   - never rejects
   */
  private async refresh(): Promise<void> {
    // 🔴 TWO try/catch BLOCKS, NOT ONE AROUND BOTH AWAITS. Legacy has two
    // separate `if (response.ok)` gates, so a failing global call still leaves
    // the tiles repainted from the first. One block around both would make the
    // second endpoint's health silently decide whether the first's numbers
    // appear — a coupling neither client has and nobody would look for.
    try {
      const stats = await this.api.get<TimeSavedStats>( TIME_SAVED_ENDPOINT );
      this.paintTiles( stats );
    } catch ( err ) {
      this.logFn( `TimeSavedRenderer: time-saved stats read failed, leaving prior values: ${ String( err ) }` );
    }

    try {
      const global = await this.api.get<GlobalTimeSavedStats>( TIME_SAVED_GLOBAL_ENDPOINT );
      this.paintSolutions( global.top_solutions );
    } catch ( err ) {
      this.logFn( `TimeSavedRenderer: global stats read failed, leaving prior leaderboard: ${ String( err ) }` );
    }
  }

  /** Write the four tiles, each with legacy's own fallback for its kind. */
  private paintTiles( stats: TimeSavedStats ): void {
    for ( const tile of TILES ) {
      const el = this.valueEls.get( tile.key );
      /* c8 ignore next */ // defensive: the map is filled from TILES at mount, so every key resolves.
      if ( el === undefined ) continue;
      const raw = stats[ tile.key ];
      el.textContent = raw !== undefined && raw !== null && raw !== "" && raw !== 0
        ? String( raw )
        : ( tile.numeric ? "0" : TIME_SAVED_PLACEHOLDER );
    }
  }

  /**
   * Repaint the leaderboard in the SERVER'S order (T4) — it is a ranking, and
   * re-sorting it here would be a second opinion about which solution is first.
   *
   * The question text goes in through `textContent`, so the escaping legacy does
   * by hand (`escapeHtml`) is done by the DOM instead. Same outcome, one fewer
   * place to get wrong.
   */
  private paintSolutions( solutions: ReadonlyArray<TopSolution> | undefined ): void {
    /* c8 ignore next */ // defensive: solutionsEl is set at mount and nulled in unmount, in lockstep with `mounted`.
    if ( this.solutionsEl === null ) return;

    if ( solutions === undefined || solutions.length === 0 ) {
      const empty = document.createElement( "p" );
      empty.className = "no-data";
      empty.textContent = TOP_SOLUTIONS_EMPTY;
      this.solutionsEl.replaceChildren( empty );
      return;
    }

    const rows = solutions.map( ( sol, idx ) => {
      const row = document.createElement( "div" );
      row.className = "top-solution-item";

      const rank = document.createElement( "span" );
      rank.className = "rank";
      rank.textContent = `#${ idx + 1 }`;

      const question = document.createElement( "span" );
      question.className = "question";
      question.textContent = sol.question ?? "";

      const stats = document.createElement( "span" );
      stats.className = "stats";
      stats.textContent = `${ sol.replays ?? 0 } replays · ${ sol.time_saved_formatted ?? TIME_SAVED_PLACEHOLDER } saved`;

      row.append( rank, question, stats );
      return row;
    } );
    this.solutionsEl.replaceChildren( ...rows );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createTimeSavedRenderer( opts: TimeSavedRendererOptions ): TimeSavedRenderer {
  return new TimeSavedRendererImpl( opts );
}
