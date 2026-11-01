// Static "About" panel — introduces the tool, its tabs and how it works.
const FEATURES: { title: string; body: string }[] = [
  {
    title: "Bot Builder",
    body: "Compose the automation as a visual block graph - ensure home, train troops, find a match, deploy, return home - with typed ports, control flow (if / loop) and live run logs.",
  },
  {
    title: "Attack Plan",
    body: "Design the army + deploy plan: order troops, spells, sieges and heroes, set drop points/lines, add delays and an end-battle/surrender step. Weighted variants pick one plan per attack.",
  },
  {
    title: "Assets",
    body: "Capture, rename, recategorise, replace and delete the template images the bot matches against - straight from the live device, with orphan-reference warnings.",
  },
  {
    title: "Device",
    body: "Scan, select and connect an emulator / device over ADB, then watch a live screen stream shared across every tab.",
  },
];

export function About() {
  return (
    <div className="about-tab">
      <div className="about-card">
        <div className="about-hero">
          <img className="about-logo" src="/logo.png" alt="coc-studio" />
          <div className="about-hero-text">
            <h1 className="about-title">coc-studio</h1>
            <p className="about-tagline">A visual automation builder for Clash of Clans.</p>
            <p className="about-lead">
              coc-studio turns a Clash of Clans farming routine into a graph you
              can see and edit. It drives an emulator over ADB, locates buttons
              and units on screen by OpenCV template matching, and runs the flow
              you build - training the army, finding a match, deploying a chosen
              plan and looping.
            </p>
          </div>
        </div>

        <div className="about-grid">
          {FEATURES.map((f) => (
            <div key={f.title} className="about-feature">
              <div className="about-feature-title">{f.title}</div>
              <div className="about-feature-body">{f.body}</div>
            </div>
          ))}
        </div>

        <div className="about-tech">
          <span className="about-tech-label">Built with</span>
          <span>React · ReactFlow · TypeScript · Vite</span>
          <span>FastAPI · Python · OpenCV · ADB</span>
        </div>

        <div className="about-footer">
          <span>coc-studio · v0.1.0</span>
          <span>
            Created by <strong>n1ghtf4ll</strong>
          </span>
          <span className="muted">For personal / authorized use only.</span>
        </div>
      </div>
    </div>
  );
}
