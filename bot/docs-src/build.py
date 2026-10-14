import json, re, html, sys, importlib.util
spec = importlib.util.spec_from_file_location("content", sys.argv[1]); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
out = sys.argv[2]
def inline(t):
    t = html.escape(t, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
for name, doc in (("terms", c.TERMS), ("privacy", c.PRIVACY)):
    parts = []
    for kind, val in doc["blocks"]:
        if kind == "h": parts.append(f"<h2>{inline(val)}</h2>")
        elif kind == "ul": parts.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in val) + "</ul>")
        elif kind == "lead": parts.append(f'<p class="lead">{inline(val)}</p>')
        elif kind == "final": parts.append(f'<p class="final">{inline(val)}</p>')
        else: parts.append(f"<p>{inline(val)}</p>")
    json.dump({"title": doc["title"], "date": c.DATE, "body": "\n".join(parts)}, open(f"{out}/{name}.json", "w"), ensure_ascii=False, indent=1)
    json.dump({"title": doc["title"], "date": c.DATE, "blocks": doc["blocks"]}, open(f"{out}/{name}.spec.json", "w"), ensure_ascii=False)
print("ok")
