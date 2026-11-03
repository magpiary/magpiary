"""Generate S2 spike Shortcuts as .shortcut files. Throwaway; from-memory format.

    python3 spikes/S2/make_shortcuts.py          # writes spikes/S2/shortcuts/unsigned/*.shortcut

Then sign each (Apple's signing service, uses the Mac's Apple ID):
    shortcuts sign --mode anyone -i unsigned/X.shortcut -o X.shortcut

The folder to save into cannot be written here (it is a device-specific bookmark), so the
config Shortcut asks where to save when it runs.
"""

import json
import plistlib
import subprocess
import tempfile
import uuid
from pathlib import Path

OUT = Path(__file__).parent / "shortcuts" / "unsigned"
OBJ = "￼"  # placeholder character for an inline variable


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def shortcut_input() -> dict:
    return {"Value": {"Type": "ExtensionInput"}, "WFSerializationType": "WFTextTokenAttachment"}


def output_of(uid: str, name: str) -> dict:
    return {"Value": {"OutputUUID": uid, "OutputName": name, "Type": "ActionOutput"}, "WFSerializationType": "WFTextTokenAttachment"}


def token_string(text: str, attachments: dict[int, dict]) -> dict:
    """Text with inline variables. attachments maps the index of OBJ in `text` to its variable."""
    return {
        "Value": {
            "string": text,
            "attachmentsByRange": {f"{{{i}, 1}}": v for i, v in attachments.items()},
        },
        "WFSerializationType": "WFTextTokenString",
    }


def icon() -> dict:
    """Teal tile. WFWorkflowIconImageData is the custom picture (newer iOS); older ones use colour + glyph."""
    out = {"WFWorkflowIconStartColor": 431817727, "WFWorkflowIconGlyphNumber": 59511}
    logo = Path(__file__).parent / "logo.png"
    if logo.exists():
        out["WFWorkflowIconImageData"] = logo.read_bytes()
    return out


def workflow(actions: list[dict]) -> dict:
    return {
        "WFWorkflowClientVersion": "900",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": icon(),
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem", "WFGenericFileContentItem"],
        "WFWorkflowTypes": [],
        "WFWorkflowActions": actions,
    }


def config_shortcut() -> dict:
    text_id, dict_id, value_id = new_id(), new_id(), new_id()
    return workflow([
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": text_id,
                "WFTextActionText": token_string(OBJ, {0: shortcut_input()["Value"]}),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.save",
            "WFWorkflowActionParameters": {
                "WFInput": output_of(text_id, "Text"),
                "WFAskWhereToSave": True,  # pick On My iPhone / Magpiary once
                "WFFileDestinationPath": "config.json",
                "WFSaveFileOverwrite": True,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.detect.dictionary",
            "WFWorkflowActionParameters": {"UUID": dict_id, "WFInput": shortcut_input()},
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": value_id,
                "WFDictionaryKey": "host",
                "WFInput": output_of(dict_id, "Dictionary"),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
            "WFWorkflowActionParameters": {
                "WFNotificationActionTitle": "Magpiary",
                "WFNotificationActionBody": token_string(
                    "Paired with " + OBJ, {len("Paired with "): output_of(value_id, "Dictionary Value")["Value"]}
                ),
            },
        },
    ])


def pair_shortcut(config: dict) -> dict:
    """Config baked in. Pings the Mac at the baked-in address and shows a friendly result."""
    text_id, ping_id, reply_id, name_id = new_id(), new_id(), new_id(), new_id()
    ping_url = f"http://{config['host']}:{config['port']}/v1/ping"
    prefix = "Your iPhone can reach "
    suffix = ".\n\nMagpiary is set up. Sharing a reel or post to Magpiary will send it to this Mac."
    return workflow([
        {   # the baked-in pairing config; later Shortcuts read host, port and key from here
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {"UUID": text_id, "WFTextActionText": json.dumps(config)},
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {"UUID": ping_id, "WFURL": ping_url, "WFHTTPMethod": "GET"},
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.detect.dictionary",
            "WFWorkflowActionParameters": {"UUID": reply_id, "WFInput": output_of(ping_id, "Contents of URL")},
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": name_id,
                "WFDictionaryKey": "name",
                "WFInput": output_of(reply_id, "Dictionary"),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.alert",
            "WFWorkflowActionParameters": {
                "WFAlertActionTitle": "\u2705 Magpiary is connected",
                "WFAlertActionMessage": token_string(
                    prefix + OBJ + suffix,
                    {len(prefix): output_of(name_id, "Dictionary Value")["Value"]},
                ),
                "WFAlertActionCancelButtonShown": False,
            },
        },
    ])


def act(identifier: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{identifier}", "WFWorkflowActionParameters": params}


def tstr(*parts) -> dict:
    """Token string from literal strings and variable dicts (as made by output_of(...)['Value'])."""
    text, attachments = "", {}
    for part in parts:
        if isinstance(part, str):
            text += part
        else:
            attachments[f"{{{len(text)}, 1}}"] = part
            text += OBJ
    return {"Value": {"string": text, "attachmentsByRange": attachments}, "WFSerializationType": "WFTextTokenString"}


def var(uid: str, name: str) -> dict:
    return output_of(uid, name)["Value"]


def date_var(uid: str, fmt: str) -> dict:
    """The Current Date variable with a date format applied in place (no Format Date action)."""
    v = dict(var(uid, "Current Date"))
    v["Aggrandizements"] = [{"Type": "WFDateFormatVariableAggrandizement", "WFDateFormatStyle": "Custom", "WFDateFormat": fmt}]
    return v


def queue_folder() -> dict:
    """The top level of On My iPhone. Phone test B (22 Oct 2026) showed this works with nothing created by
    hand: one permission prompt, saving and reading back both work. A folder path that does not exist
    (Magpiary/queue) fails, and so does leaving the folder out (iOS wires in the previous action's output)."""
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
    """Share-sheet Shortcut: queue first, send only at home, show at most ONE notification.

    Every run: build one JSON line from the shared link (empty url when run with no input, which the Mac
    ignores), append it to outbox.txt, save. If config["home_wifi"] is set and the phone is not on that
    network, show "Saved. It will send when you're home." and stop (no request, so no long timeout on mobile
    data). Otherwise POST the whole outbox. The outbox is blanked only if the Mac's reply carries
    "ack": "magpiary-ok" (an error reply such as 401/503 does not stop Shortcuts, and must not wipe the queue),
    and the Mac's own message is shown only if its reply says "notify": "yes" (a no-input run with nothing
    waiting stays quiet). A failed connection stops the Shortcut (iOS shows its own error); that cannot be caught.
    """
    keys = ("found", "clean0", "clean", "now", "rnd", "idt", "item", "old", "old_text", "raw", "trim", "save_a", "net",
            "joined", "body", "post", "reply", "msg", "ack", "notify", "blank", "save_b",
            "g_home", "e_home", "g_ack", "e_ack", "g_note", "e_note")
    ids = {k: new_id() for k in keys}
    endpoint = f"http://{config['host']}:{config['port']}/v1/items"
    home = config.get("home_wifi", "")
    headers = {
        "Value": {"WFDictionaryFieldValueItems": [{
            "WFItemType": 0,
            "WFKey": tstr("Authorization"),
            "WFValue": tstr(f"Bearer {config['key']}"),
        }]},
        "WFSerializationType": "WFDictionaryFieldValue",
    }

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
        act("text.replace", UUID=i("joined"), WFInput=tstr(var(i("trim"), "Updated Text")),
            WFReplaceTextFind="\\s*\\n\\s*", WFReplaceTextReplace=",", WFReplaceTextRegularExpression=True),
        act("gettext", UUID=i("body"), WFTextActionText=tstr('{"items":[', var(i("joined"), "Updated Text"), "]}")),
        act("downloadurl", UUID=i("post"), WFURL=endpoint, WFHTTPMethod="POST", WFHTTPBodyType="File",
            WFRequestVariable=output_of(i("body"), "Text"), WFHTTPHeaders=headers),
        act("detect.dictionary", UUID=i("reply"), WFInput=output_of(i("post"), "Contents of URL")),
        act("getvalueforkey", UUID=i("msg"), WFDictionaryKey="message", WFInput=output_of(i("reply"), "Dictionary")),
        act("getvalueforkey", UUID=i("ack"), WFDictionaryKey="ack", WFInput=output_of(i("reply"), "Dictionary")),
        act("getvalueforkey", UUID=i("notify"), WFDictionaryKey="notify", WFInput=output_of(i("reply"), "Dictionary")),
        when("g_ack", 0, "ack", "Dictionary Value", "magpiary-ok"),
        act("gettext", UUID=i("blank"), WFTextActionText=" "),
        act("documentpicker.save", UUID=i("save_b"), WFInput=output_of(i("blank"), "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath="magpiary-outbox.txt", WFSaveFileOverwrite=True,
            WFFolder=queue_folder()),
        when("g_note", 0, "notify", "Dictionary Value", "yes"),
        say(tstr(var(i("msg"), "Dictionary Value"))),
        when("g_note", 2),
        when("g_ack", 1),
        say("Saved on your phone. The Mac didn't accept it yet."),
        when("g_ack", 2),
    ]
    if home:
        tail = [
            act("getwifi", UUID=i("net"), WFNetworkDetailsNetwork="Wi-Fi", WFWiFiDetail="Network Name"),
            when("g_home", 0, "net", "Network Details", home),
            *send_block,
            when("g_home", 1),
            say("Saved. It will send when you're home."),
            when("g_home", 2),
        ]
    else:
        tail = send_block

    wf = workflow([
        # the shared item as text -> first web address -> drop everything after ? or #
        act("text.replace", UUID=i("found"), WFInput=tstr(shortcut_input()["Value"]),
            WFReplaceTextFind="(?s)^.*?(https?://[^\\s]+).*$", WFReplaceTextReplace="$1",
            WFReplaceTextRegularExpression=True),
        # drop the query and fragment, except on a YouTube watch link where ?v= is the video itself
        act("text.replace", UUID=i("clean0"), WFInput=tstr(var(i("found"), "Updated Text")),
            WFReplaceTextFind="(?<!youtube\\.com/watch)[?#].*$", WFReplaceTextReplace="", WFReplaceTextRegularExpression=True),
        # keep only v=ID on a watch link (drops si, t, feature and the like)
        act("text.replace", UUID=i("clean"), WFInput=tstr(var(i("clean0"), "Updated Text")),
            WFReplaceTextFind="(watch\\?v=[^&#]+).*$", WFReplaceTextReplace="$1", WFReplaceTextRegularExpression=True),
        act("date", UUID=i("now"), WFDateActionMode="Current Date"),
        act("number.random", UUID=i("rnd"), WFRandomNumberMinimum="100000", WFRandomNumberMaximum="999999"),
        act("gettext", UUID=i("idt"), WFTextActionText=tstr(date_var(i("now"), "yyyyMMddHHmmss"), "-", var(i("rnd"), "Random Number"))),
        act("gettext", UUID=i("item"), WFTextActionText=tstr(
            '{"id":"', var(i("idt"), "Text"), '","url":"', var(i("clean"), "Updated Text"),
            '","shared_at":"', date_var(i("now"), "yyyy-MM-dd'T'HH:mm:ssXXX"), '","source":"","note":"","v":1}')),
        # read the outbox, add the new line, save it (trimmed): this is the "queued" part
        act("documentpicker.open", UUID=i("old"), WFShowFilePicker=False, WFGetFilePath="magpiary-outbox.txt",
            WFFileErrorIfNotFound=False, WFFolder=queue_folder(), WFFile=queue_folder()),
        act("detect.text", UUID=i("old_text"), WFInput=output_of(i("old"), "File")),
        act("gettext", UUID=i("raw"), WFTextActionText=tstr(var(i("old_text"), "Text from Input"), "\n", var(i("item"), "Text"))),
        act("text.replace", UUID=i("trim"), WFInput=tstr(var(i("raw"), "Text")),
            WFReplaceTextFind="^\\s+|\\s+$", WFReplaceTextReplace="", WFReplaceTextRegularExpression=True),
        act("documentpicker.save", UUID=i("save_a"), WFInput=output_of(i("trim"), "Updated Text"),
            WFAskWhereToSave=False, WFFileDestinationPath="magpiary-outbox.txt", WFSaveFileOverwrite=True,
            WFFolder=queue_folder()),
        *tail,
    ])
    wf["WFWorkflowTypes"] = ["ActionExtension"]
    wf["WFWorkflowHasShortcutInputVariables"] = True
    wf["WFWorkflowInputContentItemClasses"] = ["WFURLContentItem", "WFStringContentItem", "WFSafariWebPageContentItem"]
    return wf


def test_folder(variant: str):
    """Where the folder test writes. A: no folder given (iOS default). B: root of On My iPhone.
    C: the 'Shortcuts' folder on the iPhone. All untested; the point of the test is to see which one works
    with nothing created by hand."""
    if variant == "A":
        return None
    sub = "" if variant == "B" else "Shortcuts"
    return {"displayName": sub or "On My iPhone", "filename": sub or "On My iPhone",
            "fileLocation": {"WFFileLocationType": "LocalStorage",
                             "fileProviderDomainID": "com.apple.FileProvider.LocalStorage",
                             "relativeSubpath": sub}}


def share_test_shortcut(variant: str) -> dict:
    """Share-sheet test of file access. Saves the time first (no read before write), reads it back and shows
    it in ONE notification (alerts may not show from a share sheet). X: top of On My iPhone.
    Y: a 'Magpiary' folder that does not exist yet (does Save File create it?)."""
    ids = {k: new_id() for k in ("now", "txt", "save", "back", "back_text")}
    sub = "" if variant == "X" else "Magpiary"
    folder = {"displayName": sub or "On My iPhone", "filename": sub or "On My iPhone",
              "fileLocation": {"WFFileLocationType": "LocalStorage",
                               "fileProviderDomainID": "com.apple.FileProvider.LocalStorage",
                               "relativeSubpath": sub}}
    wf = workflow([
        act("date", UUID=ids["now"], WFDateActionMode="Current Date"),
        act("gettext", UUID=ids["txt"], WFTextActionText=tstr("saved at ", date_var(ids["now"], "HH:mm:ss"))),
        act("documentpicker.save", UUID=ids["save"], WFInput=output_of(ids["txt"], "Text"),
            WFAskWhereToSave=False, WFFileDestinationPath="magpiary-share-test.txt", WFSaveFileOverwrite=True,
            WFFolder=folder),
        act("documentpicker.open", UUID=ids["back"], WFShowFilePicker=False, WFGetFilePath="magpiary-share-test.txt",
            WFFileErrorIfNotFound=False, WFFolder=folder, WFFile=folder),
        act("detect.text", UUID=ids["back_text"], WFInput=output_of(ids["back"], "File")),
        act("notification", WFNotificationActionTitle=f"Share test {variant}",
            WFNotificationActionBody=tstr("file holds: ", var(ids["back_text"], "Text from Input"))),
    ])
    wf["WFWorkflowTypes"] = ["ActionExtension"]
    wf["WFWorkflowHasShortcutInputVariables"] = True
    wf["WFWorkflowInputContentItemClasses"] = ["WFURLContentItem", "WFStringContentItem", "WFSafariWebPageContentItem"]
    return wf


def folder_test_shortcut(variant: str) -> dict:
    """Appends the time to magpiary-test.txt, saves it, reads it back and shows the whole file.
    Run it twice: if the second run shows two lines, saving and reading back both work in that location."""
    ids = {k: new_id() for k in ("now", "old", "old_text", "raw", "trim", "save", "back", "back_text")}
    folder = test_folder(variant)
    extra = {"WFFolder": folder} if folder else {}
    open_extra = {"WFFolder": folder, "WFFile": folder} if folder else {}
    return workflow([
        act("date", UUID=ids["now"], WFDateActionMode="Current Date"),
        act("documentpicker.open", UUID=ids["old"], WFShowFilePicker=False, WFGetFilePath="magpiary-test.txt",
            WFFileErrorIfNotFound=False, **open_extra),
        act("detect.text", UUID=ids["old_text"], WFInput=output_of(ids["old"], "File")),
        act("gettext", UUID=ids["raw"], WFTextActionText=tstr(var(ids["old_text"], "Text from Input"), "\n",
                                                              date_var(ids["now"], "HH:mm:ss"))),
        act("text.replace", UUID=ids["trim"], WFInput=tstr(var(ids["raw"], "Text")),
            WFReplaceTextFind="^\\s+|\\s+$", WFReplaceTextReplace="", WFReplaceTextRegularExpression=True),
        act("documentpicker.save", UUID=ids["save"], WFInput=output_of(ids["trim"], "Updated Text"),
            WFAskWhereToSave=False, WFFileDestinationPath="magpiary-test.txt", WFSaveFileOverwrite=True, **extra),
        act("documentpicker.open", UUID=ids["back"], WFShowFilePicker=False, WFGetFilePath="magpiary-test.txt",
            WFFileErrorIfNotFound=False, **open_extra),
        act("detect.text", UUID=ids["back_text"], WFInput=output_of(ids["back"], "File")),
        act("alert", WFAlertActionTitle=f"Test {variant}: file now holds",
            WFAlertActionMessage=tstr(var(ids["back_text"], "Text from Input")), WFAlertActionCancelButtonShown=False),
    ])


def sign(workflow_dict: dict, attempts: int = 4) -> bytes:
    """Sign with Apple's service via the macOS `shortcuts` tool. Retries: the service failed once with
    "Failed to modify some records" and worked on the next try. Raises if every attempt fails."""
    import time
    last = ""
    for n in range(attempts):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.shortcut", Path(tmp) / "out.shortcut"
            src.write_bytes(plistlib.dumps(workflow_dict, fmt=plistlib.FMT_BINARY))
            run = subprocess.run(
                ["shortcuts", "sign", "--mode", "anyone", "-i", str(src), "-o", str(dst)],
                capture_output=True, text=True, timeout=60,
            )
            if run.returncode == 0 and dst.exists():
                return dst.read_bytes()
            last = run.stderr.strip()[:200]
        time.sleep(2 * (n + 1))
    raise RuntimeError(f"shortcuts sign failed after {attempts} attempts: {last}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, wf in {"Magpiary Config": config_shortcut()}.items():
        path = OUT / f"{name}.shortcut"
        path.write_bytes(plistlib.dumps(wf, fmt=plistlib.FMT_BINARY))
        print("wrote", path)


if __name__ == "__main__":
    main()
