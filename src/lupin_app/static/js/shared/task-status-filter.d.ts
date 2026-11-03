// Type declaration for the shared task-list status filter.
//
// The implementation is plain JS because it must also load as a browser module on the
// classic-script notifications page, which has no build step.

/** One chip: its key, its button label and the store statuses it stands for. */
export interface TaskStatusChip {
    key      : string;
    label    : string;
    statuses : string[];
}

/** The table of chips. The claimed and review mapping is provisional. */
export declare const TASK_STATUS_CHIPS: TaskStatusChip[];

/** The chips that really filter, in table order. An empty list means All. */
export declare function activeChips( selected: string[] ): string[];

/** The selection after a click on a chip. Clearing the last chip, or all four, gives []. */
export declare function toggleChip( selected: string[], key: string ): string[];

/** The rows the selection shows. All returns every row in order. */
export declare function filterTasksByChips< T extends { status?: string | null } >( tasks: T[], selected: string[] ): T[];

/** Puts the surface on a window object as `LUPIN_TASK_STATUS_FILTER`. */
export declare function publishOnWindow( win: object ): void;
