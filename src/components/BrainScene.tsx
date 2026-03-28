import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Suspense } from "react";
import { BrainMesh } from "./BrainMesh";
import { SynapseNodes } from "./SynapseNodes";

interface BrainSceneProps {
  isUnderAttack: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  attackedNodeIndex: number | null;
  selectedNode: number | null;
  onSelectNode: (index: number | null) => void;
}

export function BrainScene({
  isUnderAttack,
  expanded,
  onToggleExpand,
  attackedNodeIndex,
  selectedNode,
  onSelectNode,
}: BrainSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 0, 5], fov: 50 }}
      style={{ width: "100%", height: "100%" }}
      gl={{ antialias: true, alpha: true }}
    >
      <ambientLight intensity={0.3} />
      <pointLight position={[10, 10, 10]} intensity={0.5} />
      <Suspense fallback={null}>
        <BrainMesh
          isUnderAttack={isUnderAttack}
          onClick={onToggleExpand}
        />
        {expanded && (
          <SynapseNodes
            isUnderAttack={isUnderAttack}
            attackedNodeIndex={attackedNodeIndex}
            selectedNode={selectedNode}
            onSelectNode={onSelectNode}
          />
        )}
      </Suspense>
      <OrbitControls
        enableZoom={false}
        enablePan={false}
        autoRotate
        autoRotateSpeed={0.5}
        minPolarAngle={Math.PI / 3}
        maxPolarAngle={(2 * Math.PI) / 3}
      />
    </Canvas>
  );
}
