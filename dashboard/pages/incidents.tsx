import { useEffect, useState } from 'react';

export default function Incidents() {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
  useEffect(()=>{
    (async()=>{
      const a = await fetch(base + '/admin/incidents');
      const b = await fetch(base + '/admin/stats');
      setIncidents((await a.json()).incidents || []);
      setStats(await b.json());
    })();
  },[]);
  return (
    <main style={{padding:20}}>
      <h1>Incidents</h1>
      {stats && (
        <div style={{margin:'8px 0', fontFamily:'monospace'}}>
          total={stats.total} status={JSON.stringify(stats.by_status)} bucket={JSON.stringify(stats.by_bucket)}
        </div>
      )}
      <table style={{width:'100%', borderCollapse:'collapse'}}>
        <thead>
          <tr>
            <th align="left">id</th>
            <th align="left">bucket</th>
            <th align="left">score</th>
            <th align="left">signature</th>
            <th align="left">updated</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i)=> (
            <tr key={i.id}>
              <td>{i.id}</td>
              <td>{i.bucket}</td>
              <td>{i.score}</td>
              <td>{i.signature}</td>
              <td>{i.last_update}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
