import { CheckCircle } from "lucide-react";

export function StatusBar() {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 pointer-events-none">
      <div className="flex items-center justify-center pb-1.5">
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground/60">
          <CheckCircle className="w-3 h-3 text-success/60" />
          <span>All systems operational</span>
          <span className="text-muted-foreground/30">·</span>
          <span className="tabular-nums">v2.4.1</span>
        </div>
      </div>
    </div>
  );
}
