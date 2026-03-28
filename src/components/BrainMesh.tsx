import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface BrainMeshProps {
  isUnderAttack: boolean;
  onClick: () => void;
}

export function BrainMesh({ isUnderAttack, onClick }: BrainMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const particlesRef = useRef<THREE.Points>(null);
  const colorRef = useRef(new THREE.Color("#22C55E"));
  const targetColor = useMemo(
    () => new THREE.Color(isUnderAttack ? "#EF4444" : "#22C55E"),
    [isUnderAttack]
  );

  // Create particle positions on a sphere surface (neural pathways)
  const particleData = useMemo(() => {
    const count = 800;
    const positions = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const phi = Math.acos(2 * Math.random() - 1);
      const theta = 2 * Math.PI * Math.random();
      const r = 1.15 + (Math.random() - 0.5) * 0.3;
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) * 0.85;
      positions[i * 3 + 2] = r * Math.cos(phi);
      sizes[i] = Math.random() * 2 + 1;
    }
    return { positions, sizes, count };
  }, []);

  useFrame((_, delta) => {
    // Smoothly interpolate color
    colorRef.current.lerp(targetColor, delta * 3);

    if (meshRef.current) {
      const mat = meshRef.current.material as THREE.MeshStandardMaterial;
      mat.emissive.copy(colorRef.current);
      mat.emissiveIntensity = isUnderAttack ? 0.6 : 0.3;
    }

    if (glowRef.current) {
      const mat = glowRef.current.material as THREE.MeshBasicMaterial;
      mat.color.copy(colorRef.current);
      const pulse = 1 + Math.sin(Date.now() * 0.003) * 0.05;
      glowRef.current.scale.setScalar(pulse);
    }

    if (particlesRef.current) {
      const mat = particlesRef.current.material as THREE.PointsMaterial;
      mat.color.copy(colorRef.current);
      particlesRef.current.rotation.y += delta * 0.1;
    }
  });

  return (
    <group>
      {/* Core brain shape — icosahedron for organic feel */}
      <mesh ref={meshRef} onClick={onClick} scale={[1, 0.85, 1]}>
        <icosahedronGeometry args={[1, 4]} />
        <meshStandardMaterial
          color="#0A0E1A"
          emissive="#22C55E"
          emissiveIntensity={0.3}
          wireframe
          transparent
          opacity={0.7}
        />
      </mesh>

      {/* Inner glow sphere */}
      <mesh ref={glowRef} scale={[0.95, 0.8, 0.95]}>
        <sphereGeometry args={[1, 32, 32]} />
        <meshBasicMaterial
          color="#22C55E"
          transparent
          opacity={0.08}
        />
      </mesh>

      {/* Neural pathway particles */}
      <points ref={particlesRef} scale={[1, 0.85, 1]}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[particleData.positions, 3]}
            count={particleData.count}
          />
        </bufferGeometry>
        <pointsMaterial
          color="#22C55E"
          size={0.02}
          transparent
          opacity={0.6}
          sizeAttenuation
          depthWrite={false}
        />
      </points>
    </group>
  );
}
