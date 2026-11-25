import { useEffect, useState } from "react";

export function App() {
  const [health, setHealth] = useState<string>("…");
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setHealth(d.status))
      .catch(() => setHealth("nicht erreichbar"));
  }, []);
  return (
    <main style={{ fontFamily: "system-ui", padding: 24 }}>
      <h1>dock</h1>
      <p>Backend: {health}</p>
    </main>
  );
}
