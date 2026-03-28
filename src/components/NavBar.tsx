import { Brain } from "lucide-react";

export function NavBar() {
  return (
    <nav className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-6 py-4 bg-background/60 backdrop-blur-sm border-b border-border/20">
      <div className="flex items-center gap-2">
        <Brain className="w-5 h-5 text-primary" />
        <span className="text-lg font-semibold tracking-tight text-foreground">
          AEGIS
        </span>
        <span className="text-xs text-muted-foreground ml-1 hidden sm:inline">
          Digital Immune System
        </span>
      </div>
      <div className="flex items-center gap-6 text-sm text-muted-foreground">
        <span className="hover:text-foreground transition-colors cursor-pointer">
          Monitor
        </span>
        <span className="hover:text-foreground transition-colors cursor-pointer hidden sm:inline">
          Logs
        </span>
        <span className="hover:text-foreground transition-colors cursor-pointer hidden sm:inline">
          Docs
        </span>
      </div>
    </nav>
  );
}
