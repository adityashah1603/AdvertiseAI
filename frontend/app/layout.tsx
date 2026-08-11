import type { Metadata } from "next";
import Link from "next/link";
import { BarChart3, Layers, Settings2, Sparkles } from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "CharacterQuilt",
  description: "Brand-agnostic ad generation pipeline",
};

// Rail items beyond "Agent work" (Knowledge/Design/Settings) aren't built in
// this trial - shown for the shell's shape, deliberately disabled rather
// than wired to nothing. Only Agent work (this app's actual surface: submit
// + review requests) is a real, clickable route.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="rail">
            <div className="logo-mark">CQ</div>
            <Link href="/" className="rail-item active" title="Agent work">
              <Sparkles size={18} />
            </Link>
            <span className="rail-item disabled" title="Knowledge (not part of this build)">
              <Layers size={18} />
            </span>
            <span className="rail-item disabled" title="Design (not part of this build)">
              <BarChart3 size={18} />
            </span>
            <span className="rail-item disabled" title="Settings (not part of this build)">
              <Settings2 size={18} />
            </span>
          </aside>
          <div className="shell-main">
            <header className="topbar">
              <span className="admin-mode">
                <span className="dot" />
                Admin mode
              </span>
              <nav style={{ display: "flex", gap: "1.25rem" }}>
                <Link href="/new-campaign">New request</Link>
                <Link href="/onboard">Onboard a brand</Link>
              </nav>
            </header>
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
