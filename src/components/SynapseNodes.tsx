import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";

const NODES = [
  { name: "Firewall", desc: "Network perimeter defense layer", icon: "🛡️" },
  { name: "API Gateway", desc: "Request routing & rate limiting", icon: "🔌" },
  { name: "Database", desc: "Persistent data store cluster", icon: "🗄️" },
  { name: "Auth Service", desc: "Identity & access management", icon: "🔐" },
  { name: "Load Balancer", desc: "Traffic distribution engine", icon: "⚖️" },
  { name: "DNS", desc: "Domain name resolution service", icon: "🌐" },
];

interface SynapseNodesProps {
  isUnderAttack: boolean;
  attackedNodeIndex: number | null;
  selectedNode: number | null;
  onSelectNode: (index: number | null) => void;
}

function SynapseNode({
  node,
  index,
  total,
  isAttacked,
  isSelected,
  onSelect,
  progress,
}: {
  node: (typeof NODES)[0];
  index: number;
  total: number;
  isAttacked: boolean;
  isSelected: boolean;
  onSelect: () => void;
  progress: number;
}) {
  const ref = useRef<THREE.Group>(null);
  const lineRef = useRef<THREE.Line>(null);

  const angle = (index / total) * Math.PI * 2;
  const targetPos = useMemo(
    () =>
      new THREE.Vector3(
        Math.cos(angle) * 2.8,
        Math.sin(angle) * 2.2,
        (Math.random() - 0.5) * 1.2
      ),
    [angle]
  );

  const currentPos = useMemo(() => new THREE.Vector3(0, 0, 0), []);

  useFrame(() => {
    if (!ref.current) return;
    currentPos.lerpVectors(
      new THREE.Vector3(0, 0, 0),
      targetPos,
      Math.min(progress, 1)
    );
    ref.current.position.copy(currentPos);

    // Update synapse line
    if (lineRef.current) {
      const geom = lineRef.current.geometry as THREE.BufferGeometry;
      const positions = geom.attributes.position;
      if (positions) {
        positions.setXYZ(0, 0, 0, 0);
        positions.setXYZ(1, currentPos.x, currentPos.y, currentPos.z);
        positions.needsUpdate = true;
      }
    }
  });

  const nodeColor = isAttacked ? "#EF4444" : "#22C55E";

  return (
    <>
      {/* Synapse line */}
      <line ref={lineRef as any}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[new Float32Array([0, 0, 0, 0, 0, 0]), 3]}
            count={2}
          />
        </bufferGeometry>
        <lineBasicMaterial
          color={nodeColor}
          transparent
          opacity={0.3}
        />
      </line>

      {/* Node */}
      <group ref={ref}>
        <mesh onClick={(e) => { e.stopPropagation(); onSelect(); }}>
          <sphereGeometry args={[0.12, 16, 16]} />
          <meshStandardMaterial
            color={nodeColor}
            emissive={nodeColor}
            emissiveIntensity={isAttacked ? 1.5 : 0.5}
          />
        </mesh>
        {/* Outer ring */}
        <mesh>
          <ringGeometry args={[0.16, 0.19, 32]} />
          <meshBasicMaterial
            color={nodeColor}
            transparent
            opacity={0.4}
            side={THREE.DoubleSide}
          />
        </mesh>

        {/* Label */}
        {progress > 0.8 && (
          <Html
            center
            distanceFactor={6}
            style={{ pointerEvents: isSelected ? "auto" : "none" }}
          >
            <div
              onClick={(e) => { e.stopPropagation(); onSelect(); }}
              style={{ pointerEvents: "auto" }}
              className="select-none cursor-pointer"
            >
              <div
                className="px-2 py-1 rounded text-xs font-medium whitespace-nowrap"
                style={{
                  background: "rgba(10,14,26,0.85)",
                  border: `1px solid ${nodeColor}40`,
                  color: nodeColor,
                  backdropFilter: "blur(8px)",
                  transform: "translateY(-24px)",
                }}
              >
                {node.icon} {node.name}
              </div>
              {isSelected && (
                <div
                  className="mt-1 px-3 py-2 rounded-lg text-xs max-w-[180px]"
                  style={{
                    background: "rgba(10,14,26,0.92)",
                    border: `1px solid ${nodeColor}30`,
                    color: "#cbd5e1",
                    backdropFilter: "blur(12px)",
                    transform: "translateY(-20px)",
                  }}
                >
                  <div className="font-semibold mb-1" style={{ color: nodeColor }}>
                    {node.name}
                  </div>
                  <div>{node.desc}</div>
                  <div className="mt-1 flex items-center gap-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full inline-block"
                      style={{ background: nodeColor }}
                    />
                    <span style={{ color: nodeColor, fontSize: 10 }}>
                      {isAttacked ? "COMPROMISED" : "ONLINE"}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </Html>
        )}
      </group>
    </>
  );
}

export function SynapseNodes({
  isUnderAttack,
  attackedNodeIndex,
  selectedNode,
  onSelectNode,
}: SynapseNodesProps) {
  const progressRef = useRef(0);
  const progressVal = useRef(0);

  useFrame((_, delta) => {
    progressRef.current = Math.min(progressRef.current + delta * 1.5, 1);
    progressVal.current = progressRef.current;
  });

  return (
    <group>
      {NODES.map((node, i) => (
        <SynapseNode
          key={node.name}
          node={node}
          index={i}
          total={NODES.length}
          isAttacked={isUnderAttack && attackedNodeIndex === i}
          isSelected={selectedNode === i}
          onSelect={() => onSelectNode(selectedNode === i ? null : i)}
          progress={progressVal.current}
        />
      ))}
    </group>
  );
}
