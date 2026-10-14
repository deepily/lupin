console.log( "Loading constants.js..." );
// These constants will be parsed by the multimodal munger object, and should be listed from top to bottom by longest string first.

/**
 * The phrase that makes the munger return the cut command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. Matching is by prefix, so a transcription that begins with "cut" matches.
 */
export const VOX_CMD_CUT            = "cut";
/**
 * The phrase that makes the munger return the copy command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_COPY           = "copy";
/**
 * The phrase that makes the munger return the paste command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. It is the longest of the edit phrases, so it is tried first.
 */
export const VOX_CMD_PASTE          = "paste from clipboard";
/**
 * The phrase that makes the munger return the delete command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_DELETE         = "delete";
/**
 * The phrase that makes the munger return the select-all command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_SELECT_ALL     = "select all";
/**
 * The five edit phrases as a list.
 *
 * The munger skips this line, because its value is a list and not one quoted phrase. Nothing else in this repository reads it.
 */
export const VOX_EDIT_COMMANDS   = [ VOX_CMD_CUT, VOX_CMD_COPY, VOX_CMD_PASTE, VOX_CMD_DELETE, VOX_CMD_SELECT_ALL ];

/**
 * The phrase that makes the munger return the close-tab command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_TAB_CLOSE        = "close current tab";
/**
 * The phrase that makes the munger return the tab-back command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_TAB_BACK         = "go backwards";
/**
 * The phrase that makes the munger return the tab-forward command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_TAB_FORWARD      = "go forwards";
/**
 * The phrase that makes the munger return the tab-refresh command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_TAB_REFRESH      = "refresh current tab";
/**
 * The phrase that makes the munger return the open-in-new-tab command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder after the phrase is the address to open.
 */
export const VOX_CMD_LOAD_NEW_TAB     = "go to new tab";
/**
 * The phrase that makes the munger return the open-in-current-tab command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder after the phrase is the address to open.
 */
export const VOX_CMD_LOAD_CURRENT_TAB = "go to current tab";
/**
 * Five tab phrases as a list, without the open-in-current-tab phrase.
 *
 * The munger skips this line, because its value is a list and not one quoted phrase. Nothing else in this repository reads it.
 */
export const VOX_TAB_COMMANDS       = [ VOX_CMD_TAB_BACK, VOX_CMD_TAB_FORWARD, VOX_CMD_TAB_REFRESH, VOX_CMD_TAB_CLOSE, VOX_CMD_LOAD_NEW_TAB ];

/**
 * The phrase that makes the munger return the open-editor command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_OPEN_EDITOR    = "open editor";

/**
 * The phrase that makes the munger return the open-file command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_OPEN_FILE      = "open file";
/**
 * The phrase for the open-url-bucket command, which the munger never loads.
 *
 * There is no space before the equals sign, so the munger's split on a spaced equals finds one piece and skips the line. Nothing else in this repository reads it.
 */
export const VOX_CMD_OPEN_URL_BUCKET= "open url bucket";
/**
 * The phrase that makes the munger return the proofread-SQL command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_PROOFREAD_SQL  = "translate to sequel";

/**
 * The phrase that makes the munger return the proofread-Python command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_PROOFREAD_PYTHON = "translate to python";
/**
 * The phrase that makes the munger return the proofread command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The stem "proof" below is a prefix of it.
 */
export const VOX_CMD_PROOFREAD      = "proofread";
/**
 * The stem "proof", which also matches any transcription that starts "proofread".
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. Longer phrases are tried first, so "proofread" wins when both match.
 */
export const VOX_CMD_PROOFREAD_STEM = "proof";
/**
 * The stem "view constan", which matches both "view constant" and "view constants".
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_VIEW_CONSTANTS = "view constan";
/**
 * The phrase that makes the munger return the view-job-queue command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_VIEW_JOB_QUEUE = "view running jobs";

/**
 * The phrase that makes the munger return the zoom-in command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_ZOOM_IN        = "zoom in";
/**
 * The phrase that makes the munger return the zoom-out command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_ZOOM_OUT       = "zoom out";
/**
 * The phrase that makes the munger return the zoom-reset command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_ZOOM_RESET     = "zoom reset";

/**
 * The one word "reset", which matches any transcription that begins with it.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_MODE_RESET     = "reset";
/**
 * The one word "exit", which matches any transcription that begins with it.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_MODE_EXIT      = "exit";
/**
 * The phrase that makes the munger return the set-link-mode command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the mode to set.
 */
export const VOX_CMD_SET_LINK_MODE  = "set link mode";
/**
 * The link-mode name "drill down", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const LINK_MODE_DRILL_DOWN   = "drill down";
/**
 * The link-mode name "new tab", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const LINK_MODE_NEW_TAB      = "new tab";

/**
 * The link-mode name "current tab", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const LINK_MODE_CURRENT_TAB  = "current tab";
/**
 * The link mode used when none is named: `LINK_MODE_DRILL_DOWN`.
 *
 * The munger skips this line, because the value is a name and not a quoted phrase. Nothing else in this repository reads it.
 */
export const LINK_MODE_DEFAULT      = LINK_MODE_DRILL_DOWN;

/**
 * The phrase that makes the munger return the set-prompt-mode command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the mode to set.
 */
export const VOX_CMD_SET_PROMPT_MODE  = "set prompt mode";
/**
 * The prompt-mode name "verbose", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const PROMPT_MODE_VERBOSE      = "verbose";
/**
 * The prompt-mode name "quiet", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const PROMPT_MODE_QUIET        = "quiet";
/**
 * The prompt mode used when none is named: `PROMPT_MODE_VERBOSE`.
 *
 * The munger skips this line, because the value is a name and not a quoted phrase. Nothing else in this repository reads it.
 */
export const PROMPT_MODE_DEFAULT      = PROMPT_MODE_VERBOSE;

/**
 * The phrase for a DuckDuckGo search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_DDG_NEW_TAB                          = "search new tab";
/**
 * The phrase for a DuckDuckGo search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_DDG_CURRENT_TAB                      = "search current tab";
/**
 * The phrase for a Google search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_GOOGLE_NEW_TAB                       = "search google new tab";
/**
 * The phrase for a Google search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_GOOGLE_CURRENT_TAB                   = "search google current tab";
/**
 * The phrase for a Phind search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_PHIND_NEW_TAB                        = "search phind new tab";
/**
 * The phrase for a Phind search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_PHIND_CURRENT_TAB                    = "search phind current tab";
/**
 * The phrase for a Perplexity search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_PERPLEXITY_NEW_TAB                   = "search perplexity new tab";
/**
 * The phrase for a Perplexity search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_PERPLEXITY_CURRENT_TAB               = "search perplexity current tab";
/**
 * The phrase for a Google Scholar search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_GOOGLE_SCHOLAR_NEW_TAB               = "search google scholar new tab";
/**
 * The phrase for a Google Scholar search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the search text.
 */
export const VOX_CMD_SEARCH_GOOGLE_SCHOLAR_CURRENT_TAB           = "search google scholar current tab";

/**
 * The phrase for a DuckDuckGo clipboard search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_DDG_NEW_TAB                = "search using clipboard new tab";
/**
 * The phrase for a DuckDuckGo clipboard search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_DDG_CURRENT_TAB            = "search using clipboard current tab";
/**
 * The phrase for a Google clipboard search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_GOOGLE_NEW_TAB             = "search google using clipboard new tab";
/**
 * The phrase for a Google clipboard search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_GOOGLE_CURRENT_TAB         = "search google using clipboard current tab";
/**
 * The phrase for a Phind clipboard search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_PHIND_NEW_TAB              = "search phind using clipboard new tab";
/**
 * The phrase for a Phind clipboard search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_PHIND_CURRENT_TAB          = "search phind using clipboard current tab";
/**
 * The phrase for a Perplexity clipboard search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_PERPLEXITY_NEW_TAB         = "search perplexity using clipboard new tab";
/**
 * The phrase for a Perplexity clipboard search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_PERPLEXITY_CURRENT_TAB     = "search perplexity using clipboard current tab";
/**
 * The phrase for a Google Scholar clipboard search in a new tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_GOOGLE_SCHOLAR_NEW_TAB     = "search google scholar using clipboard new tab";
/**
 * The phrase for a Google Scholar clipboard search in the current tab.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The phrase names the clipboard, so the remainder is not the search text.
 */
export const VOX_CMD_SEARCH_CLIPBOARD_GOOGLE_SCHOLAR_CURRENT_TAB = "search google scholar using clipboard current tab";



/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_text_contact`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const MULTIMODAL_CONTACT_INFO  = "multimodal contact information";
/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_python_punctuation`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const MULTIMODAL_PYTHON_PUNCTUATION = "multimodal python punctuation";

/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_python_proofread`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const MULTIMODAL_PYTHON_PROOFREAD = "multimodal python proofread";
/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_text_email`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const MULTIMODAL_TEXT_EMAIL    = "multimodal text email";
/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_vox_cmd_browser`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const STEM_MULTIMODAL_BROWSER  = "multimodal browser";
/**
 * The mode phrase that multimodal_munger.py spells as `trans_mode_vox_cmd_agent`.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The two spellings are separate literals.
 */
export const STEM_MULTIMODAL_AGENT    = "multimodal agent";
/**
 * The mode phrase of `trans_mode_server_search`, which the munger never loads from here.
 *
 * The line has no closing semicolon, so the munger's check for a closing quote and semicolon fails and skips it. The same phrase is spelled in multimodal_munger.py.
 */
export const STEM_MULTIMODAL_SERVER_SEARCH = "multimodal server search"

/**
 * The phrase that makes the munger return the run-prompt command.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`. The remainder is the suffix that says where the prompt comes from.
 */
export const VOX_CMD_RUN_PROMPT           = "run prompt";
/**
 * The suffix "from file", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const VOX_CMD_SUFFIX_FROM_FILE     = "from file";
/**
 * The suffix "from clipboard", which the munger never loads.
 *
 * There is no space before the equals sign, so the munger's split on a spaced equals finds one piece and skips the line. Nothing else in this repository reads it.
 */
export const VOX_CMD_SUFFIX_FROM_CLIPBOARD= "from clipboard";

/**
 * The phrase for the save-from-clipboard command, which the munger never loads.
 *
 * There is no space before the equals sign, so the munger's split on a spaced equals finds one piece and skips the line. Nothing else in this repository reads it.
 */
export const VOX_CMD_SAVE_FROM_CLIPBOARD= "save from clipboard";

/**
 * The recorder mode name "transcription mode", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const MODE_TRANSCRIPTION       = "transcription mode";
/**
 * The recorder mode name "command-mode", with a hyphen, which is also a munger phrase.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const MODE_COMMAND             = "command-mode";
/**
 * The recorder mode name "agent mode", which is also a phrase the munger matches.
 *
 * `MultiModalMunger._get_command_strings` lists this phrase. A transcription that equals it, or starts with it, matches, and the rest becomes `args`.
 */
export const MODE_AGENT               = "agent mode";

/**
 * The address of the speech server, on this machine at port 5002.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const TTS_SERVER_ADDRESS        = "http://127.0.0.1:5002";
/**
 * The address of the Lupin server, on this machine at port 7999.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const GIB_SERVER_ADDRESS        = "http://127.0.0.1:7999";

/**
 * The page address of the quill editor, served on this machine at port 8080.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const EDITOR_URL                = "http://127.0.0.1:8080/genie-plugin-firefox/html/editor-quill.html";
/**
 * The page address of the blank page, served on this machine at port 8080.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const BUCKET_URL                = "http://127.0.0.1:8080/genie-plugin-firefox/html/blank.html";
/**
 * The address of the plugin's own constants file, served at port 8080 on this machine.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const CONSTANTS_URL             = "http://127.0.0.1:8080/genie-plugin-firefox/js/constants.js";
/**
 * The search page address of Google.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const SEARCH_URL_GOOGLE         = "https://www.google.com/search";
/**
 * The search page address of Google Scholar.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const SEARCH_URL_GOOGLE_SCHOLAR = "https://scholar.google.com/scholar";
/**
 * The search page address of DuckDuckGo.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const SEARCH_URL_DDG            = "https://www.duckduckgo.com/";
/**
 * The search page address of Phind.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const SEARCH_URL_PHIND          = "https://www.phind.com/search";
/**
 * The search page address of Perplexity.
 *
 * The munger skips values that start with a quoted http scheme. Nothing else in this repository reads it.
 */
export const SEARCH_URL_PERPLEXITY     = "https://www.perplexity.ai/search";

/**
 * The zoom step, 0.075 of the page size.
 *
 * The munger skips this line, because the value is a number and not a quoted phrase. Nothing else in this repository reads it.
 */
export const ZOOM_INCREMENT = 0.075;
/**
 * The largest zoom factor, 5.
 *
 * The munger skips this line, because the value is a number and not a quoted phrase. Nothing else in this repository reads it.
 */
export const ZOOM_MAX       = 5;
/**
 * The smallest zoom factor, 0.3.
 *
 * The munger skips this line, because the value is a number and not a quoted phrase. Nothing else in this repository reads it.
 */
export const ZOOM_MIN       = 0.3;
/**
 * The zoom factor of an unzoomed page, 1.
 *
 * The munger skips this line, because the value is a number and not a quoted phrase. Nothing else in this repository reads it.
 */
export const ZOOM_DEFAULT   = 1;

console.log( "Loading constants.js... Done!" );