"""A throwaway hub on fictional data with one long post (item 1: long summary, many takeaways, long transcript) and one short post (item 2),
for post-bars.sh. Never touches the real library. Usage: post_bars_hub.py DATA_DIR PORT THEME   (THEME: indigo or dark)"""
import json, os, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
(root/"home").mkdir(parents=True, exist_ok=True); (root/"cfg").mkdir(parents=True, exist_ok=True)
os.environ["MAGPIARY_HOME"]=str(root/"home"); os.environ["MAGPIARY_CONFIG"]=str(root/"cfg")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from magpiary.hub import details_from_folder
from magpiary.receiver import make_server
from magpiary.store import Store
store=Store(root/"home"/"magpiary.db"); store.set_setting("setup_done","1"); store.set_setting("ui_theme", sys.argv[3])
lib=root/"home"/"library"
srv=make_server(store,"127.0.0.1",int(sys.argv[2])); srv.hub.library=lib
lorem=" ".join(f"Sentence {i} about the example editing workflow where the reference set guides visual designs and sound choices." for i in range(40))
posts=[("https://www.youtube.com/watch?v=LongVideo01","youtube","How to Edit Viral Talking Head Videos Using Only Claude",lorem,60),
       ("https://www.youtube.com/watch?v=ShortVideo2","youtube","Short example post","A tiny summary.",2)]
for i,(url,src,title,summ,nseg) in enumerate(posts):
    f=lib/f"{src}-{i}"; f.mkdir(parents=True,exist_ok=True)
    (f/"meta.json").write_text(json.dumps({"url":url,"source":src,"title":title,"text":lorem if nseg>10 else "Short caption","author":"Dev Example"}))
    (f/"record.json").write_text(json.dumps({"title":title,"summary":summ,"tags":["claude","editing"],"extras":{"takeaways":[f"Takeaway {k} "+lorem[:80] for k in range(12 if nseg>10 else 1)]}}))
    (f/"transcript.json").write_text(json.dumps({"segments":[{"start":k*4,"end":k*4+3,"text":f"Transcript line {k} where the speaker explains the workflow in some detail."} for k in range(nseg)]}))
    if store.get_item(url) is None: store.add_link(url)
    store.fetch_succeeded(url,str(f)); store.set_details(url,details_from_folder(f))
pile=store.new_pile("Dinner ideas"); store.move_to_pile(posts[0][0],pile)
print("READY",srv.server_port,store.id_for(posts[0][0]),store.id_for(posts[1][0]),pile,flush=True)
srv.serve_forever()
