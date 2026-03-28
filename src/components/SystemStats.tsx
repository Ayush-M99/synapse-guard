import { Server, Globe, Database, ShieldCheck } from "lucide-react";

const glass =
  "backdrop-blur-xl border rounded-lg px-4 py-3 border-border/20 bg-card/40";

const nodes = [
  { name: "Firewall", status: "online", latency: "2ms" },
  { name: "API Gateway", status: "online", latency: "4ms" },
  { name: "Auth Service", status: "online", latency: "3ms" },
  { name: "Database", status: "online", latency: "6ms" },
  { name: "Load Balancer", status: "online", latency: "1ms" },
  { name: "DNS", status: "online", latency: "5ms" },
];

export function SystemStats() {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 pointer-events-none">
      <div className="px-6 pb-5 flex items-end justify-between gap-4 pointer-events-auto flex-wrap">
        {/* Node status grid */}
        <div className={`${glass} max-w-md`}>
          <div className="flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-wider mb-3">
            <Server className="w-3.5 h-3.5" />
            Active Nodes
            <span className="ml-auto text-foreground font-medium text-xs">
              6/6 Online
            </span>
          </div>
          <div className="grid grid-cols-3 gap-x-6 gap-y-1.5">
            {nodes.map((node) => (
              <div
                key={node.name}
                className="flex items-center gap-1.5 text-xs"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                <span className="text-muted-foreground">{node.name}</span>
                <span className="ml-auto text-foreground/60 tabular-nums text-[10px]">
                  {node.latency}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Security posture */}
        <div className={`${glass} min-w-[200px]`}>
          <div className="flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-wider mb-2">
            <ShieldCheck className="w-3.5 h-3.5" />
            Security Posture
          </div>
          <div className="flex items-center gap-3">
            <div className="text-3xl font-bold text-success">A+</div>
            <div className="text-[10px] text-muted-foreground leading-relaxed">
              <div>TLS 1.3 enforced</div>
              <div>Zero trust architecture</div>
              <div>Last audit: 2h ago</div>
            </div>
          </div>
        </div>

        {/* Traffic summary */}
        <div className={`${glass} min-w-[180px]`}>
          <div className="flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-wider mb-2">
            <Globe className="w-3.5 h-3.5" />
            Traffic
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Requests/s</span>
              <span className="text-foreground tabular-nums font-medium">
                4,821
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Bandwidth</span>
              <span className="text-foreground tabular-nums font-medium">
                1.2 GB/s
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">Geo regions</span>
              <span className="text-foreground tabular-nums font-medium">
                14 active
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
