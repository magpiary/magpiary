"""Generates the iPhone Shortcut ("Magpiary") for one phone, with its Mac address and key baked in.

Ported from the M0 spike (spikes/S2/make_shortcuts.py), keeping every fix proven on a real phone:
the link is read as text with a regex (Get URLs from Input yields nothing), the queue is one text
file at the top of On My iPhone, nothing is ever deleted, the outbox is blanked only when the
reply carries the ack string, and exactly one notification is shown per run. The file format is
written from memory and verified on the phone; see docs/findings/S2-S3-S6-shortcut.md.
"""

import hashlib
import plistlib
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from magpiary.protocol import ACK, BOARDS_PATH, DEFAULT_RETRY_WAIT, ITEMS_PATH, SIGN_DEVICE, SIGN_SIG, SIGN_TIME, device_tag

OBJ = "￼"  # placeholder character for an inline variable
OUTBOX = "magpiary-outbox.txt"
BOARDS = "magpiary-boards.txt"  # the Mac's list of active boards, refreshed by every reply
WIFI = "magpiary-wifi.txt"  # where this phone may send, "home" or "any", refreshed by every reply
TRY = "magpiary-try.txt"  # "<Wi-Fi name>¦<slot>" written before a send and cleared once the Mac answers: a note left
#                         behind means the last try on that network got no answer (a failed connection cannot be caught)
SEP = "\u00a7"
GO = "@@go@@"
BLK = "@@blk@@"
# A "slot" is yyyyMMddHHmm with its minutes folded into a letter, so a try note lasts to the end of its slot. Each rule is one
# Replace Text (regular expression) step; the minutes are the last two digits. 5 minutes keeps the tens digit and folds the units.
SLOT_RULES = {
    5: (("[0-4]$", "a"), ("[5-9]$", "b")),
    15: (("(?:0[0-9]|1[0-4])$", "a"), ("(?:1[5-9]|2[0-9])$", "b"), ("(?:3[0-9]|4[0-4])$", "c"), ("(?:4[5-9]|5[0-9])$", "d")),
    30: (("[0-2][0-9]$", "a"), ("[3-5][0-9]$", "b")),
    60: (("[0-5][0-9]$", ""),),
}
LIBRARY_ONLY = "Just my library"

# Phone-side cleaning (three regular expressions proven in M0). The Mac cleans again.
FIND_LINK = "(?s)^.*?(https?://[^\\s]+).*$"
DROP_TAIL = "(?<!youtube\\.com/watch)[?#].*$"
KEEP_VIDEO_ID = "(watch\\?v=[^&#]+).*$"


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def shortcut_input() -> dict:
    return {"Value": {"Type": "ExtensionInput"}, "WFSerializationType": "WFTextTokenAttachment"}


def output_of(uid: str, name: str) -> dict:
    return {"Value": {"OutputUUID": uid, "OutputName": name, "Type": "ActionOutput"},
            "WFSerializationType": "WFTextTokenAttachment"}


def var(uid: str, name: str) -> dict:
    return output_of(uid, name)["Value"]


def tstr(*parts) -> dict:
    """Token string from literal strings and variable dicts (as made by var(...))."""
    text, attachments = "", {}
    for part in parts:
        if isinstance(part, str):
            text += part
        else:
            attachments[f"{{{len(text)}, 1}}"] = part
            text += OBJ
    return {"Value": {"string": text, "attachmentsByRange": attachments}, "WFSerializationType": "WFTextTokenString"}


def date_var(uid: str, fmt: str) -> dict:
    """The Current Date variable with a date format applied in place (no Format Date action)."""
    v = dict(var(uid, "Current Date"))
    v["Aggrandizements"] = [{"Type": "WFDateFormatVariableAggrandizement",
                             "WFDateFormatStyle": "Custom", "WFDateFormat": fmt}]
    return v


def act(identifier: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{identifier}", "WFWorkflowActionParameters": params}


def sign_steps(i, p: str, secret: str, request: str, body: str = "") -> list:
    """Sign one request on the phone (0.1.5): the time now, the body's hash when there is a body, and the hash of
    "S|request|time[|body hash]" (protocol.sign_text). Generate Hash runs on the phone: nothing is asked, nothing is sent."""
    steps = [act("date", UUID=i(p + "now"), WFDateActionMode="Current Date"),
             act("gettext", UUID=i(p + "stamp"), WFTextActionText=tstr(date_var(i(p + "now"), "yyyy-MM-dd'T'HH:mm:ssXXX")))]
    parts = [secret + f"|{request}|", var(i(p + "stamp"), "Text")]
    if body:
        steps.append(act("hash", UUID=i(p + "bhash"), WFHashType="SHA256", WFInput=output_of(body, "Text")))
        parts += ["|", var(i(p + "bhash"), "Hash")]
    return steps + [act("gettext", UUID=i(p + "src"), WFTextActionText=tstr(*parts)),
                    act("hash", UUID=i(p + "sig"), WFHashType="SHA256", WFInput=output_of(i(p + "src"), "Text"))]


def signed_headers(i, p: str, tag: str) -> dict:
    """Who is sending, when, and the signature; never the key."""
    fields = ((SIGN_DEVICE, tstr(tag)), (SIGN_TIME, tstr(var(i(p + "stamp"), "Text"))), (SIGN_SIG, tstr(var(i(p + "sig"), "Hash"))))
    return {"Value": {"WFDictionaryFieldValueItems": [{"WFItemType": 0, "WFKey": tstr(k), "WFValue": v} for k, v in fields]},
            "WFSerializationType": "WFDictionaryFieldValue"}


def queue_folder() -> dict:
    """The top level of On My iPhone: needs nothing created by hand (phone test B, 22 Oct 2026).
    A folder path that does not exist fails, and so does leaving the folder out."""
    return {
        "displayName": "On My iPhone",
        "filename": "On My iPhone",
        "fileLocation": {
            "WFFileLocationType": "LocalStorage",
            "fileProviderDomainID": "com.apple.FileProvider.LocalStorage",
            "relativeSubpath": "",
        },
    }


def share_shortcut(config: dict) -> dict:
    """The share-sheet Shortcut: queue first, send only at home, show at most ONE notification.

    config: host (the Mac's .local name), port, key, and optionally home_wifi. The Shortcut holds only sha256(key) and
    signs each request with it (sign_steps); the key itself is never in it, so it never crosses the Wi-Fi.

    Every run builds one JSON line from the shared link (an empty url when run with no input, which the
    Mac ignores), appends it to the outbox file and saves. Then `send_gate` decides: with a home_wifi, send on
    that network (or on any Wi-Fi when the Mac says "any"); without one, send on any Wi-Fi (unless the Mac says
    "home"); run by hand with nothing shared, always send. When it says no (mobile data, or the wrong network) it
    shows one "Saved…" notification and stops (no request, so no long timeout). Otherwise it POSTs the whole outbox. The outbox is blanked only if the reply carries the
    ack string (an error reply such as 401 or 503 does not stop Shortcuts, and must not wipe the queue), and
    the Mac's own message is shown only if the reply says notify=yes. A failed connection stops the Shortcut
    (iOS shows its own error); that cannot be caught.
    """
    keys = ("found", "clean0", "clean", "now", "rnd", "idt", "item", "old", "old_text", "raw", "trim", "save_a",
            "net", "wopen", "wtxt", "mopen", "mtxt", "slot0", "slot1", "slot2", "slot3", "slot", "cur", "gate", "gmatch", "gblk", "g_blk", "e_blk",
            "tsave_a", "tsave_b", "cblank_a", "cblank_b", "csave_a", "csave_b", "wval", "wtext", "wsave", "fwval", "fwtext", "fwsave", "joined", "body", "post", "reply", "msg", "ack", "notify", "blank", "save_b",
            "g_go", "e_go", "g_ack", "e_ack", "g_note", "e_note",
            "bfile", "btext", "bactive", "blines", "bnames", "bmenu", "bsplit", "bpick", "bid0", "bid", "g_link", "e_link", "g_any", "e_any", "blist", "blist2", "bsave",
            "g_fgo", "e_fgo", "fget", "fdict", "fval", "ftext", "fsave", "g_fack", "e_fack",
            "oset0", "bline", "bline2", "braw", "btrim", "bqsave", "oset1",
            "snow", "sstamp", "sbhash", "ssrc", "ssig", "fnow", "fstamp", "fsrc", "fsig")
    ids = {k: new_id() for k in keys}
    endpoint = f"http://{config['host']}:{config['port']}{ITEMS_PATH}"
    home = config.get("home_wifi", "")
    secret = hashlib.sha256(config["key"].encode()).hexdigest()
    tag = device_tag(secret)

    def i(k: str) -> str:
        return ids[k]

    def when(gk, mode, src=None, name="", text=""):
        if mode == 0:
            return act("conditional", GroupingIdentifier=i(gk), WFControlFlowMode=0, WFCondition="Contains",
                       WFInput={"Type": "Variable", "Variable": output_of(i(src), name)},
                       WFConditionalActionString=tstr(text))
        return act("conditional", GroupingIdentifier=i(gk), WFControlFlowMode=mode,
                   **({"UUID": i("e_" + gk.split("_")[1])} if mode == 2 else {}))

    def say(text) -> dict:
        return act("notification", WFNotificationActionTitle="Magpiary", WFNotificationActionBody=text)

    send_block = [
        act("text.replace", UUID=i("joined"), WFInput=tstr({"Type": "Variable", "VariableName": "outbox"}),
            WFReplaceTextFind="\\s*\\n\\s*", WFReplaceTextReplace=",", WFReplaceTextRegularExpression=True),
        act("gettext", UUID=i("body"), WFTextActionText=tstr('{"items":[', var(i("joined"), "Updated Text"), "]}")),
        *sign_steps(i, "s", secret, f"POST {ITEMS_PATH}", body=i("body")),
        *try_mark(i, "b"),
        act("downloadurl", UUID=i("post"), WFURL=endpoint, WFHTTPMethod="POST", WFHTTPBodyType="File",
            WFRequestVariable=output_of(i("body"), "Text"), WFHTTPHeaders=signed_headers(i, "s", tag)),
        act("detect.dictionary", UUID=i("reply"), WFInput=output_of(i("post"), "Contents of URL")),
        *try_clear(i, "b"),
        act("getvalueforkey", UUID=i("msg"), WFDictionaryKey="message", WFInput=output_of(i("reply"), "Dictionary")),
        act("getvalueforkey", UUID=i("ack"), WFDictionaryKey="ack", WFInput=output_of(i("reply"), "Dictionary")),
        act("getvalueforkey", UUID=i("notify"), WFDictionaryKey="notify", WFInput=output_of(i("reply"), "Dictionary")),
        when("g_ack", 0, "ack", "Dictionary Value", ACK),
        # the Mac's list of active boards, kept for the next share (also when away from home)
        act("getvalueforkey", UUID=i("blist"), WFDictionaryKey="boards", WFInput=output_of(i("reply"), "Dictionary")),
        act("gettext", UUID=i("blist2"), WFTextActionText=tstr(var(i("blist"), "Dictionary Value"), "\n")),
        act("documentpicker.save", UUID=i("bsave"), WFInput=output_of(i("blist2"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=BOARDS, WFSaveFileOverwrite=True, WFFolder=queue_folder()),
        # where this phone may send (Settings → Phones on the Mac), kept for the next run
        act("getvalueforkey", UUID=i("wval"), WFDictionaryKey="wifi", WFInput=output_of(i("reply"), "Dictionary")),
        act("gettext", UUID=i("wtext"), WFTextActionText=tstr(var(i("wval"), "Dictionary Value"))),
        act("documentpicker.save", UUID=i("wsave"), WFInput=output_of(i("wtext"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=WIFI, WFSaveFileOverwrite=True, WFFolder=queue_folder()),
        act("gettext", UUID=i("blank"), WFTextActionText=" "),
        act("documentpicker.save", UUID=i("save_b"), WFInput=output_of(i("blank"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=OUTBOX, WFSaveFileOverwrite=True,
            WFFolder=queue_folder()),
        when("g_note", 0, "notify", "Dictionary Value", "yes"),
        say(tstr(var(i("msg"), "Dictionary Value"))),
        when("g_note", 2),
        when("g_ack", 1),
        say("Saved on your phone. The Mac didn't accept it yet."),
        when("g_ack", 2),
    ]
    tail = [
        when("g_go", 0, "gmatch", "Updated Text", GO),
        *send_block,
        when("g_go", 1),
        # blocked by a try that got no answer a moment ago on this network, or not on a network to send on
        when("g_blk", 0, "gblk", "Updated Text", BLK),
        say("Saved. Your Mac wasn't reachable on this Wi-Fi a moment ago. It will send when it is, or run Magpiary "
            "from Shortcuts to try now."),
        when("g_blk", 1),
        say("Saved. It will send when you're home." if home else "Saved. It will send when you're on Wi-Fi."),
        when("g_blk", 2),
        when("g_go", 2),
    ]

    actions = [
        # the shared item as text -> first web address -> drop everything after ? or #
        act("text.replace", UUID=i("found"), WFInput=tstr(shortcut_input()["Value"]),
            WFReplaceTextFind=FIND_LINK, WFReplaceTextReplace="$1", WFReplaceTextRegularExpression=True),
        # drop the query and fragment, except on a YouTube watch link where ?v= is the video itself
        act("text.replace", UUID=i("clean0"), WFInput=tstr(var(i("found"), "Updated Text")),
            WFReplaceTextFind=DROP_TAIL, WFReplaceTextReplace="", WFReplaceTextRegularExpression=True),
        # keep only v=ID on a watch link (drops si, t, feature and the like)
        act("text.replace", UUID=i("clean"), WFInput=tstr(var(i("clean0"), "Updated Text")),
            WFReplaceTextFind=KEEP_VIDEO_ID, WFReplaceTextReplace="$1", WFReplaceTextRegularExpression=True),
        act("date", UUID=i("now"), WFDateActionMode="Current Date"),
        act("number.random", UUID=i("rnd"), WFRandomNumberMinimum="100000", WFRandomNumberMaximum="999999"),
        act("gettext", UUID=i("idt"),
            WFTextActionText=tstr(date_var(i("now"), "yyyyMMddHHmmss"), "-", var(i("rnd"), "Random Number"))),
        act("gettext", UUID=i("item"), WFTextActionText=tstr(
            '{"id":"', var(i("idt"), "Text"), '","url":"', var(i("clean"), "Updated Text"),
            '","shared_at":"', date_var(i("now"), "yyyy-MM-dd'T'HH:mm:ssXXX"), '","source":"","note":"","v":1}')),
        *send_gate(i, home, int(config.get("retry_wait", DEFAULT_RETRY_WAIT))),
        # a phone-test build only: show what the gate saw before anything else happens
        *([say(tstr("note=[", var(i("mtxt"), "Text from Input"), "] now=[", var(i("cur"), "Text"), "] go=[",
                    var(i("gmatch"), "Updated Text"), "]"))] if config.get("debug") else []),
        # read the outbox, add the new line, save it (trimmed): this is the "queued" part
        act("documentpicker.open", UUID=i("old"), WFShowFilePicker=False, WFGetFilePath=OUTBOX,
            WFFileErrorIfNotFound=False, WFFolder=queue_folder(), WFFile=queue_folder()),
        act("detect.text", UUID=i("old_text"), WFInput=output_of(i("old"), "File")),
        act("gettext", UUID=i("raw"),
            WFTextActionText=tstr(var(i("old_text"), "Text from Input"), "\n", var(i("item"), "Text"))),
        act("text.replace", UUID=i("trim"), WFInput=tstr(var(i("raw"), "Text")),
            WFReplaceTextFind="^\\s+|\\s+$", WFReplaceTextReplace="", WFReplaceTextRegularExpression=True),
        act("documentpicker.save", UUID=i("save_a"), WFInput=output_of(i("trim"), "Updated Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=OUTBOX, WFSaveFileOverwrite=True,
            WFFolder=queue_folder()),
        act("setvariable", UUID=i("oset0"), WFVariableName="outbox", WFInput=output_of(i("trim"), "Updated Text")),
        # the post is queued: only now ask about boards (a Mac that can't be reached loses nothing)
        *board_question(i, today=date_var(i("now"), "yyyyMMdd"), item_id=var(i("idt"), "Text"),
                        url=var(i("clean"), "Updated Text"),
                        refresh=fresh_boards(i, f"http://{config['host']}:{config['port']}{BOARDS_PATH}",
                                             signed_headers(i, "f", tag), True, sign_steps(i, "f", secret, f"GET {BOARDS_PATH}"))),
        *tail,
    ]
    return {
        "WFWorkflowClientVersion": "900",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        # a custom picture is ignored by iOS (tested), so only the teal tile colour and a glyph
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 431817727, "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem", "WFSafariWebPageContentItem"],
        "WFWorkflowActions": actions,
    }


def try_mark(i, tag: str) -> list:
    """Note "trying on this network now" before a request that may never come back."""
    return [act("documentpicker.save", UUID=i("tsave_" + tag), WFInput=output_of(i("cur"), "Text"),
                WFAskWhereToSave=False, WFFileDestinationPath=TRY, WFSaveFileOverwrite=True, WFFolder=queue_folder())]


def try_clear(i, tag: str) -> list:
    """The Mac answered (with anything): clear the note."""
    return [act("gettext", UUID=i("cblank_" + tag), WFTextActionText=" "),
            act("documentpicker.save", UUID=i("csave_" + tag), WFInput=output_of(i("cblank_" + tag), "Text"),
                WFAskWhereToSave=False, WFFileDestinationPath=TRY, WFSaveFileOverwrite=True, WFFolder=queue_folder())]


def gate_patterns(home: str) -> tuple[str, str]:
    """(the send decision, the "blocked by a recent unanswered try" test) as regular expressions over the gate text
    "<Wi-Fi name>§<mode>§<shared link>§<try note>§<this network and slot>§"."""
    s = SEP
    blocked = f"(?:[^{s}]*{s}){{3}}([^{s}]+){s}\\1{s}"  # the try note is this network in this very slot
    manual = f"[^{s}]*{s}[^{s}]*{s}{s}.*"                 # nothing shared: Send now, whatever the note says
    if home:
        ok = f"[^{s}]*{re.escape(home)}[^{s}]*{s}.*|[^{s}]+{s}\\s*any\\s*{s}.*"
    else:  # no home name: any Wi-Fi, unless the Mac says "home"
        ok = f"[^{s}]+{s}(?!\\s*home\\s*{s}).*"
    return f"(?is)^(?:{manual}|(?!{blocked})(?:{ok}))$", f"(?is)^{blocked}$"


def slot_steps(i, rules) -> list:
    steps, previous = [], ("slot0", "Text")
    for n, (find, letter) in enumerate(rules):
        uid = "slot" if n == len(rules) - 1 else f"slot{n + 1}"
        steps.append(act("text.replace", UUID=i(uid), WFInput=tstr(var(i(previous[0]), previous[1])), WFReplaceTextFind=find,
                         WFReplaceTextReplace=letter, WFReplaceTextRegularExpression=True))
        previous = (uid, "Updated Text")
    return steps


def send_gate(i, home: str, wait: int = DEFAULT_RETRY_WAIT) -> list:
    """Decide once whether to try sending now. Only `Contains` on an action's output is trusted in Shortcuts
    conditions (phone tests, docs/findings/S2-S3-S6-shortcut.md), so the decision is one text and one regex:
    "<Wi-Fi name>§<mode file>§<shared link>§<try note>§<network and slot>§" becomes @@go@@ when
      the phone is on its home Wi-Fi (when it has one), or
      the Mac said "any" and the phone is on some Wi-Fi (the name is not empty); a phone with no home Wi-Fi
      name counts as "any" unless the Mac says "home" ... and the last try on this network, in this 5-minute
      slot, did not go unanswered (a failed connection cannot be caught, so every try leaves a note first and
      clears it when the Mac answers); or
      Magpiary was run by hand with nothing shared (the link is empty): "Send now", always."""
    decide, blocked = gate_patterns(home)
    return [
        act("getwifi", UUID=i("net"), WFNetworkDetailsNetwork="Wi-Fi", WFWiFiDetail="Network Name"),
        act("documentpicker.open", UUID=i("wopen"), WFShowFilePicker=False, WFGetFilePath=WIFI,
            WFFileErrorIfNotFound=False, WFFolder=queue_folder(), WFFile=queue_folder()),
        act("detect.text", UUID=i("wtxt"), WFInput=output_of(i("wopen"), "File")),
        act("documentpicker.open", UUID=i("mopen"), WFShowFilePicker=False, WFGetFilePath=TRY,
            WFFileErrorIfNotFound=False, WFFolder=queue_folder(), WFFile=queue_folder()),
        act("detect.text", UUID=i("mtxt"), WFInput=output_of(i("mopen"), "File")),
        # the slot (5, 15, 30 or 60 minutes): yyyyMMddHHmm with the minutes folded into a letter
        act("gettext", UUID=i("slot0"), WFTextActionText=tstr(date_var(i("now"), "yyyyMMddHHmm"))),
        *slot_steps(i, SLOT_RULES.get(wait, SLOT_RULES[DEFAULT_RETRY_WAIT])),
        act("gettext", UUID=i("cur"), WFTextActionText=tstr(var(i("net"), "Network Details"), "\u00a6",
                                                            var(i("slot"), "Updated Text"))),
        act("gettext", UUID=i("gate"), WFTextActionText=tstr(
            var(i("net"), "Network Details"), SEP, var(i("wtxt"), "Text from Input"), SEP, var(i("clean"), "Updated Text"), SEP,
            var(i("mtxt"), "Text from Input"), SEP, var(i("cur"), "Text"), SEP)),
        act("text.replace", UUID=i("gmatch"), WFInput=tstr(var(i("gate"), "Text")), WFReplaceTextFind=decide,
            WFReplaceTextReplace=GO, WFReplaceTextRegularExpression=True),
        act("text.replace", UUID=i("gblk"), WFInput=tstr(var(i("gate"), "Text")), WFReplaceTextFind=blocked,
            WFReplaceTextReplace=BLK, WFReplaceTextRegularExpression=True),
    ]


def fresh_boards(i, endpoint: str, headers: dict, gated: bool, signing: list = ()) -> list:
    """Ask the Mac for its latest board list before the question, so a board made a moment ago shows on the very
    next share (owner, 25 Oct 2026), when the send decision says go. Otherwise the saved copy is used. The list
    (and where this phone may send) is saved only from a reply carrying the ack."""
    fetch = [
        *signing,
        *try_mark(i, "a"),
        act("downloadurl", UUID=i("fget"), WFURL=endpoint, WFHTTPMethod="GET", WFHTTPHeaders=headers),
        act("detect.dictionary", UUID=i("fdict"), WFInput=output_of(i("fget"), "Contents of URL")),
        *try_clear(i, "a"),
        act("getvalueforkey", UUID=i("fval"), WFDictionaryKey="boards", WFInput=output_of(i("fdict"), "Dictionary")),
        act("gettext", UUID=i("ftext"), WFTextActionText=tstr(var(i("fval"), "Dictionary Value"), "\n")),
        act("conditional", GroupingIdentifier=i("g_fack"), WFControlFlowMode=0, WFCondition="Contains",
            WFInput={"Type": "Variable", "Variable": output_of(i("fdict"), "Dictionary")},
            WFConditionalActionString=tstr(ACK)),
        act("documentpicker.save", UUID=i("fsave"), WFInput=output_of(i("ftext"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=BOARDS, WFSaveFileOverwrite=True, WFFolder=queue_folder()),
        act("getvalueforkey", UUID=i("fwval"), WFDictionaryKey="wifi", WFInput=output_of(i("fdict"), "Dictionary")),
        act("gettext", UUID=i("fwtext"), WFTextActionText=tstr(var(i("fwval"), "Dictionary Value"))),
        act("documentpicker.save", UUID=i("fwsave"), WFInput=output_of(i("fwtext"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=WIFI, WFSaveFileOverwrite=True, WFFolder=queue_folder()),
        act("conditional", GroupingIdentifier=i("g_fack"), WFControlFlowMode=2, UUID=i("e_fack")),
    ]
    if not gated:
        return fetch
    return [
        act("conditional", GroupingIdentifier=i("g_fgo"), WFControlFlowMode=0, WFCondition="Contains",
            WFInput={"Type": "Variable", "Variable": output_of(i("gmatch"), "Updated Text")},
            WFConditionalActionString=tstr(GO)),
        *fetch,
        act("conditional", GroupingIdentifier=i("g_fgo"), WFControlFlowMode=2, UUID=i("e_fgo")),
    ]


def board_question(i, today: dict, item_id: dict, url: dict, refresh: list = ()) -> list:
    """"Add it to a board too?", asked only when something was shared and a board is active today (owner, 25 Oct
    2026), after the post is already queued.

    The boards file holds the Mac's last list (fetched just before at home): one "DAYS<TAB>Name<TAB>id" line per
    active board, DAYS being the dates it stays active. Lines without today's date are dropped, so a board goes
    quiet on time even away from home. "Just my library" comes first. A board choice is queued as one more line for
    the same post ({"attach":1,"board":id}); the library choice leaves no line."""
    def cond(gk: str, mode: int, src: str = "", name: str = "", text: str = "") -> dict:
        if mode == 0:
            return act("conditional", GroupingIdentifier=i(gk), WFControlFlowMode=0, WFCondition="Contains",
                       WFInput={"Type": "Variable", "Variable": output_of(i(src), name)},
                       WFConditionalActionString=tstr(text))
        return act("conditional", GroupingIdentifier=i(gk), WFControlFlowMode=mode,
                   **({"UUID": i("e_" + gk.split("_")[1])} if mode == 2 else {}))

    def replace(uid: str, src: dict, find, to: str = "") -> dict:
        return act("text.replace", UUID=i(uid), WFInput=src, WFReplaceTextFind=find, WFReplaceTextReplace=to,
                   WFReplaceTextRegularExpression=True)

    outbox = {"Type": "Variable", "VariableName": "outbox"}
    return [
        cond("g_link", 0, "clean", "Updated Text", "http"),
        *refresh,
        act("documentpicker.open", UUID=i("bfile"), WFShowFilePicker=False, WFGetFilePath=BOARDS,
            WFFileErrorIfNotFound=False, WFFolder=queue_folder(), WFFile=queue_folder()),
        act("detect.text", UUID=i("btext"), WFInput=output_of(i("bfile"), "File")),
        replace("bactive", tstr(var(i("btext"), "Text from Input")), tstr("(?m)^(?!.*", today, ").*(\n|$)")),
        replace("blines", tstr(var(i("bactive"), "Updated Text")), "(?m)^[0-9 ]+\t"),
        cond("g_any", 0, "blines", "Updated Text", "\t"),
        replace("bnames", tstr(var(i("blines"), "Updated Text")), "\t[0-9a-f]{16}"),
        act("gettext", UUID=i("bmenu"), WFTextActionText=tstr(LIBRARY_ONLY + "\n", var(i("bnames"), "Updated Text"))),
        act("text.split", UUID=i("bsplit"), text=output_of(i("bmenu"), "Text"), WFTextSeparator="New Lines"),
        act("choosefromlist", UUID=i("bpick"), WFInput=output_of(i("bsplit"), "Split Text"),
            WFChooseFromListActionPrompt="Add it to a board too?"),
        replace("bid0", tstr(var(i("blines"), "Updated Text")),
                tstr("(?s)^(?:.*\n)?", var(i("bpick"), "Chosen Item"), "\t([0-9a-f]{16}).*$"), "$1"),
        replace("bid", tstr(var(i("bid0"), "Updated Text")), "(?s)^(?![0-9a-f]{16}$).*$"),
        act("gettext", UUID=i("bline"), WFTextActionText=tstr(
            '{"id":"', item_id, '-b","url":"', url, '","board":"', var(i("bid"), "Updated Text"), '","attach":1,"v":1}')),
        replace("bline2", tstr(var(i("bline"), "Text")), '(?s)^.*"board":"",.*$'),  # Just my library: no line
        act("gettext", UUID=i("braw"), WFTextActionText=tstr(outbox, "\n", var(i("bline2"), "Updated Text"))),
        replace("btrim", tstr(var(i("braw"), "Text")), "^\\s+|\\s+$"),
        act("documentpicker.save", UUID=i("bqsave"), WFInput=output_of(i("btrim"), "Updated Text"),
            WFAskWhereToSave=False, WFFileDestinationPath=OUTBOX, WFSaveFileOverwrite=True, WFFolder=queue_folder()),
        act("setvariable", UUID=i("oset1"), WFVariableName="outbox", WFInput=output_of(i("btrim"), "Updated Text")),
        cond("g_any", 2),
        cond("g_link", 2),
    ]


def sign(workflow: dict, attempts: int = 3) -> bytes:
    """Sign with Apple's service via the macOS `shortcuts` tool (needs the network). It failed once with
    "Failed to modify some records" and worked on the next try, so retry. Raises if every attempt fails."""
    last = ""
    for n in range(attempts):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.shortcut", Path(tmp) / "out.shortcut"
            src.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
            try:
                run = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "-i", str(src), "-o", str(dst)],
                                     capture_output=True, text=True, timeout=40)
            except (OSError, subprocess.SubprocessError) as err:
                last = type(err).__name__
            else:
                if run.returncode == 0 and dst.exists():
                    return dst.read_bytes()
                # newer macOS prints dozens of harmless "Unrecognized attribute string flag" lines first; the real reason is after them
                last = " | ".join(ln for ln in run.stderr.splitlines() if ln.strip() and "Unrecognized attribute" not in ln)[:300] or run.stderr.strip()[:200]
        time.sleep(2 * (n + 1))
    raise RuntimeError(f"shortcuts sign failed after {attempts} attempts: {last}")
