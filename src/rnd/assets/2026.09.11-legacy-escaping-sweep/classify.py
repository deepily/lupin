"""Classify every row of review.tsv (the 276 not safe-by-shape) into a category.
Rulings are keyed on (line, code-prefix) at sha 69bfa03c; any row no rule claims is UNCLASSIFIED."""
import sys, re, collections

REVIEW_TSV, OUT_TSV = sys.argv[ 1 ], sys.argv[ 2 ]
rows = [ l.rstrip( "\n" ).split( "\t" ) for l in open( REVIEW_TSV ) if l.strip() ]

SENDER   = "A sender-supplied, unescaped"
OPERATOR = "B operator's own input, unescaped"
SERVER   = "C server-generated, unescaped"
VALID    = "D server-validated shape (sender_id pattern / regex-derived)"
SAFE     = "E safe: escaped, sanitized, literal, numeric, id, or a swept fragment"

# Explicit rulings, by line → (category, why). Line numbers at 69bfa03c.
RULINGS = {
    23165 : ( SENDER,   "action-required title: notification.title || message" ),
    23120 : None,  # two rows on this line, split below
    23861 : ( SENDER,   "multiple-choice question text" ),
    23782 : ( SENDER,   "multiple-choice option description" ),
    21757 : ( SENDER,   "minimized action-required card: truncated notification.message" ),
    20191 : ( SENDER,   "notification list: [PREFIX] split of the sender message" ),
    20231 : None,  # displayMessage / message / priority
    19071 : ( SENDER,   "sender card: session_name (<=64 chars, no pattern) or words of the first message" ),
    24682 : ( SENDER,   "expired badge: response_default the sender declared" ),
    23491 : ( SENDER,   "prediction hint: 'header: value' — header comes from the sender's response_options" ),
    23819 : ( OPERATOR, "multiple-choice 'Other' input value: the operator's saved custom answer" ),
    24562 : ( OPERATOR, "responded badge: the operator's own response" ),
    24762 : ( OPERATOR, "responded-elsewhere badge: the operator's own response from another device" ),
    6748  : None,  # questionSafe / id_hash
    4525  : ( SERVER,   "TTS error modal text (TTS envelope)" ),
    4526  : ( SERVER,   "TTS error modal code (TTS envelope)" ),
    8558  : None,
    8681  : ( SERVER,   "top solutions stats (server computed)" ),
    7498  : ( SERVER,   "job agent_type (server set)" ),
    7739  : ( SERVER,   "job agent_type (server set)" ),
    23492 : ( SERVER,   "prediction strategy label, raw strategy on fallback (server computed)" ),
    15972 : ( SERVER,   "persona colour (INI)" ),
    15973 : ( SERVER,   "persona label (INI)" ),
    15974 : ( SERVER,   "persona icon (INI)" ),
    15975 : ( SERVER,   "persona label (INI)" ),
    7697  : ( SERVER,   "report link section: server paths; yamlPath escaped with escapeHtml inside a JS string in an onclick (wrong context)" ),
    8544  : ( SAFE,     "formatResponseValue: every return path goes through escapeHtml" ),
    8556  : ( VALID,    "interaction priority (enum validated at the notify door), literal fallback" ),
    10184 : ( SAFE,     "ROW_SCHEMA field name (page constant)" ),
    10337 : ( SAFE,     "ROW_SCHEMA field name (page constant)" ),
    10529 : ( SAFE,     "option(): literal verb value/label" ),
    10530 : ( SAFE,     "option(): literal verb value/label, reason is a literal or deadReason (status via _escapeTaskAttr)" ),
    20063 : ( SAFE,     "createHistoryWindowDropdown: WINDOW_OPTIONS page constant" ),
    20067 : ( SAFE,     "createHistoryWindowDropdown: WINDOW_OPTIONS page constant" ),
    20069 : ( SAFE,     "createHistoryWindowDropdown: WINDOW_OPTIONS page constant" ),
    20070 : ( SAFE,     "createHistoryWindowDropdown: WINDOW_OPTIONS page constant" ),
    23386 : ( SAFE,     "batch question counter (numbers)" ),
    20229 : ( VALID,    "notification type upper-cased (enum validated at the notify door)" ),
    20230 : ( VALID,    "notification priority (enum validated at the notify door)" ),
}

def rule( line, kind, detail, code ):
    line = int( line )
    if line == 23120:
        return ( SENDER, "open-ended input value: response_default" ) if "response_default" in code else ( SAFE, "notification.id" )
    if line == 23778:
        return ( SENDER, "multiple-choice option label (value attribute)" ) if code == "opt.label" else ( SAFE, "questionId template" )
    if line == 23781:
        return ( SENDER, "multiple-choice option label (text)" )
    if line == 20231:
        if code == "displayMessage": return ( SENDER, "notification list: displayed message" )
        if code == "message":        return ( SENDER, "notification list: message inside title=\"\"" )
        if code == "priority":       return ( VALID,  "notification priority (enum validated at the notify door)" )
    if line == 10332:
        return ( SAFE, "ROW_SCHEMA field name (page constant)" ) if code == "f" else ( SAFE, "row field part built with escapeHtml/_escapeTaskAttr in _rowFieldParts" )
    if line == 6748:
        if code == "questionSafe": return ( OPERATOR, "history retry button: the operator's own question, escaped for ' and \" only, inside a JS string in onclick" )
        return ( SAFE, "job id_hash" )
    if line == 8558:
        return ( SERVER, "interaction type (server enum)" ) if code == "interaction.type" else ( SAFE, "type icon lookup with literal fallback" )
    if line in RULINGS and RULINGS[ line ] is not None:
        return RULINGS[ line ]

    # Pattern rules for the remainder
    c, d = code, detail
    if re.search( r"\bsessionId\b|escapedSenderId|senderId\.replace|projectName|\bproject\b$", c ) or "getProjectFromSenderId" in d or "senderId.replace" in d:
        return ( VALID, "derived from sender_id, which the notify door validates against a strict pattern" )
    if c == "senderId" or c == "dateString":
        return ( VALID, "sender_id (pattern-validated) / date key" )
    if "renderMarkdownInline" in c or "renderMarkdown" in c or "renderAbstractSection" in c:
        return ( SAFE, "marked + DOMPurify, or escapeHtml when either is missing" )
    if "_escapeTaskAttr" in c or "_escapeTaskAttr" in d:
        return ( SAFE, "_escapeTaskAttr (& \" < >)" )
    if re.search( r"\.id\b|id_hash|job_id|notification\.id|\bidKey\b|\bjobId\b|\bid\b$|jobIdDisplay|idSlug|idAttr", c ):
        return ( SAFE, "server id / slug" )
    if re.search( r"toFixed|toLocaleString|toISOString|toLocale(Date|Time)String|\.length\b|\+ 1$|totalCount|\bwidth\b|_rowWidth|total$|totalQuestions|queuePosition|questionIndex|\bidx\b|timeoutDisplay|formatTimeoutDisplay", c + " " + d ):
        return ( SAFE, "number, count, width or formatted date" )
    if re.search( r"timestamp|timeStr|\btime\b|\bts\b|schedDateStr|schedTimeStr|formatJobTimestamp|duration", c + " " + d ):
        return ( SAFE, "formatted timestamp / duration" )
    if re.search( r"template|call:\S*\.map\(|\.join\b|sections\.join|headerRow|HeaderRow|_render|render[A-Z]|build[A-Z]|discLine|_disclosureToggle|chevron|Html\b|HTML\b|\bhtml\b|\bbody\b|\bcells\b|\brows\b|\bheads\b|\bfields\b|\boptions\b|responseUI|disclosed|deleteBtn|deleteAction|cancelBtnHtml|completionBadge|scheduledBadge|statusIndicator|personaBadge|voteControls|groupHeaderHtml|verdictClass|_fleetVerdictClass|_taskStatusClass|statusClass|rowClass|\bsel\(", c + " " + d ):
        return ( SAFE, "HTML fragment whose own interpolations are swept separately, or a class-name helper" )
    if re.search( r"\?\s*' — ' \+ reason|pctClass|extraClass|\bdetail\b|conversationMode|typeIcon|glyph|\bf\b$|parts\[ f \]|\bmodifier\b|\blabel\b$|\bvalue\b$|\bwhy\b$|headerLabel|\bkey\b$|epicAttr|ownerAttr", c + " " + d ):
        return ( SAFE, "escaped upstream, literal, or a schema field name" )
    return ( "UNCLASSIFIED", "" )

out = collections.OrderedDict()
lines = []
for line, kind, detail, code in rows:
    cat, why = rule( line, kind, detail, code )
    out.setdefault( cat, [] ).append( ( int( line ), code, why ) )
    lines.append( f"{line}\t{cat[ :1 ]}\t{code}\t{why}" )

for cat, items in sorted( out.items() ):
    print( f"{len( items ):4d}  {cat}" )
for cat in ( SENDER, OPERATOR, SERVER, "UNCLASSIFIED" ):
    if cat in out:
        print( f"\n== {cat}" )
        for l, code, why in out[ cat ]: print( f"  {l:6d}  {code[ :60 ]:60s}  {why}" )
open( OUT_TSV, "w" ).write( "\n".join( lines ) + "\n" )
