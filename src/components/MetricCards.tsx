import { Shield, Clock, Zap, Server } from "lucide-react";

interface MetricCardsProps {
  threatsBlocked: number;
  isUnderAttack: boolean;
}

const glass =
  "backdrop-blur-md border rounded-lg px-4 py-3 border-border/30 bg-card/50";

export function MetricCards({ threatsBlocked, isUnderAttack }: MetricCardsProps) {
  return (
    <div className="absolute inset-0 pointer-events-none z-10">
      {/* Top-left */}
      <div className={`absolute top-20 left-6 ${glass} pointer-events-auto`}>
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          <Shield className="w-3.5 h-3.5" />
          Threats Blocked
        </div>
        <div className="text-2xl font-bold text-foreground tabular-nums">
          {threatsBlocked.toLocaleString()}
        </div>
      </div>

      {/* Top-right */}
      <div className={`absolute top-20 right-6 ${glass} pointer-events-auto`}>
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          <Clock className="w-3.5 h-3.5" />
          System Uptime
        </div>
        <div className="text-2xl font-bold text-foreground flex items-center gap-2">
          99.97%
          <span className="w-2 h-2 rounded-full bg-success inline-block animate-pulse" />
        </div>
      </div>

      {/* Bottom-left */}
      <div className={`absolute bottom-6 left-6 ${glass} pointer-events-auto`}>
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          <Zap className="w-3.5 h-3.5" />
          Response Time
        </div>
        <div className="text-2xl font-bold text-foreground">&lt; 12ms</div>
      </div>

      {/* Bottom-right */}
      <div className={`absolute bottom-6 right-6 ${glass} pointer-events-auto`}>
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          <Server className="w-3.5 h-3.5" />
          Active Nodes
        </div>
        <div className="text-2xl font-bold text-foreground">
          {isUnderAttack ? (
            <>
              <span className="text-destructive">5</span>/6
            </>
          ) : (
            "6/6"
          )}{" "}
          <span className="text-xs font-normal text-muted-foreground">Online</span>
        </div>
      </div>
    </div>
  );
}
