import { useState, useEffect, useCallback } from "react";
import { BrainScene } from "@/components/BrainScene";
import { MetricCards } from "@/components/MetricCards";
import { NavBar } from "@/components/NavBar";
import { toast } from "sonner";

const ATTACK_INTERVAL = 15000;
const HEAL_DELAY = 3000;

const Index = () => {
  const [isUnderAttack, setIsUnderAttack] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [threatsBlocked, setThreatsBlocked] = useState(142);
  const [attackedNodeIndex, setAttackedNodeIndex] = useState<number | null>(null);
  const [selectedNode, setSelectedNode] = useState<number | null>(null);

  const triggerAttack = useCallback(() => {
    const nodeIdx = Math.floor(Math.random() * 6);
    setIsUnderAttack(true);
    setAttackedNodeIndex(nodeIdx);
    toast.error("⚠ Threat Detected", {
      description: "Anomalous traffic pattern identified. Initiating response...",
      duration: HEAL_DELAY,
    });

    setTimeout(() => {
      setIsUnderAttack(false);
      setAttackedNodeIndex(null);
      setThreatsBlocked((prev) => prev + 1);
      toast.success("✓ Threat Mitigated", {
        description: "System integrity restored. All nodes operational.",
        duration: 3000,
      });
    }, HEAL_DELAY);
  }, []);

  useEffect(() => {
    const interval = setInterval(triggerAttack, ATTACK_INTERVAL);
    return () => clearInterval(interval);
  }, [triggerAttack]);

  return (
    <div className="relative w-full h-screen overflow-hidden bg-background">
      <NavBar />
      <MetricCards threatsBlocked={threatsBlocked} isUnderAttack={isUnderAttack} />
      <div className="absolute inset-0">
        <BrainScene
          isUnderAttack={isUnderAttack}
          expanded={expanded}
          onToggleExpand={() => {
            setExpanded((e) => !e);
            setSelectedNode(null);
          }}
          attackedNodeIndex={attackedNodeIndex}
          selectedNode={selectedNode}
          onSelectNode={setSelectedNode}
        />
      </div>

      {/* Instruction hint */}
      {!expanded && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 text-xs text-muted-foreground animate-pulse">
          Click the brain to reveal neural synapses
        </div>
      )}
    </div>
  );
};

export default Index;
