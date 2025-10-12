import { useState } from 'react';

export default function Preview() {
  const [text, setText] = useState("");
  const [res, setRes] = useState<any>(null);
  const run = async () => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    const r = await fetch(base + "/admin/preview?text=" + encodeURIComponent(text));
    setRes(await r.json());
  };
  return (
    <div style={{padding:20}}>
      <textarea style={{width:'100%',height:160}} value={text} onChange={e=>setText(e.target.value)} placeholder="Paste a Help Scout message..." />
      <div style={{marginTop:8}}>
        <button onClick={run}>Preview</button>
      </div>
      {res && <pre style={{fontSize:12, background:'#f7f7f7', padding:12}}>{JSON.stringify(res,null,2)}</pre>}
    </div>
  );
}
