import { Brain, Bell } from "lucide-react";

export function NavBar() {
  return (
    <nav className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-6 h-14 bg-background/70 backdrop-blur-xl border-b border-border/10">
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-md bg-primary/10 border border-primary/20 flex items-center justify-center">
          <Brain className="w-4 h-4 text-primary" />
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-tight text-foreground leading-none">
            AEGIS
          </span>
          <span className="text-[10px] text-muted-foreground leading-none mt-0.5">
            Digital Immune System
          </span>
        </div>
      </div>

      <div className="flex items-center gap-6 text-[13px] text-muted-foreground">
        <span className="hover:text-foreground transition-colors cursor-pointer">
          Dashboard
        </span>
        <span className="hover:text-foreground transition-colors cursor-pointer hidden sm:inline">
          Analytics
        </span>
        <span className="hover:text-foreground transition-colors cursor-pointer hidden sm:inline">
          Nodes
        </span>
        <span className="hover:text-foreground transition-colors cursor-pointer hidden md:inline">
          Docs
        </span>
        <button className="relative hover:text-foreground transition-colors">
          <Bell className="w-4 h-4" />
          <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-success" />
        </button>
        <div className="w-7 h-7 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-xs font-medium text-primary">
          A
        </div>
      </div>
    </nav>
  );
}
