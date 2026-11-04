// The one table that names a TypeScript node kind, shared by ts_extract.js and src/scripts/ts_doc_extract.mjs.
//
// The compiler's enum maps a value back to a name, and the markers declared after a kind share its value
// (VariableStatement and FirstStatement). Reading ts.SyntaxKind[ value ] returns the last declared name, so
// the entries are reversed and the first declared name wins.
//
// It is CommonJS and takes the compiler as an argument because the two callers load the compiler differently:
// ts_extract.js requires the path its request names, and the .mjs script has a bare import. Neither could
// import the other's table.

/** Build the value-to-name map for a loaded TypeScript compiler. The first declared name of each value wins. */
module.exports = function kindNames( ts ) {
    return new Map(
        Object.entries( ts.SyntaxKind )
            .filter( ( [ , value ] ) => typeof value === "number" )
            .reverse()
            .map( ( [ name, value ] ) => [ value, name ] )
    );
};
