/**
 * The time zone for the standalone pages: the server zone, else labelled UTC.
 *
 * Pages with a login call LupinAppZone.load() once; pages without one never call it and show labelled UTC.
 * The browser's own zone is never used.
 */
const LupinAppZone = (() => {

    let zoneName = null;

    /**
     * Fetch the server zone with the page login, and log an error naming app_timezone if absent.
     *
     * Requires:
     *     - auth.js is loaded, so apiCall exists
     *
     * Ensures:
     *     - the zone is the server's value, or null after any failure
     */
    async function load() {
        zoneName = null;
        try {
            const config = await apiCall( '/api/config/client' );
            zoneName = config && config.app_timezone ? config.app_timezone : null;
            if ( !zoneName ) console.error( 'Client config carries no app_timezone: times show in UTC' );
        } catch ( error ) {
            console.error( 'Failed to fetch client config: app_timezone is unset, so times show in UTC:', error );
        }
    }

    /** Return the zone every display uses: the server zone, else UTC. */
    function zone() {
        return zoneName || 'UTC';
    }

    /** Return the label that marks a displayed time as UTC, or an empty string. */
    function label() {
        return zoneName ? '' : ' UTC';
    }

    /** Format the time of day of a date in the display zone. */
    function time( date, locale, options ) {
        return date.toLocaleTimeString( locale, { ...options, timeZone: zone() } ) + label();
    }

    /** Format the calendar date of a date in the display zone. */
    function day( date, locale, options ) {
        return date.toLocaleDateString( locale, { ...options, timeZone: zone() } ) + label();
    }

    /** Format the date and time of a date in the display zone. */
    function dateTime( date, locale, options ) {
        return date.toLocaleString( locale, { ...options, timeZone: zone() } ) + label();
    }

    return { load, zone, label, time, day, dateTime };
})();
