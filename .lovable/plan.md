

## Digital Immune System — Brain Visualization

### Hero: 3D Rotating Brain (Center Stage)
- A glowing, slowly rotating 3D brain rendered with **React Three Fiber** (`@react-three/fiber@^8.18`, `three@^0.160`, `@react-three/drei@^9.122.0`)
- Brain is a stylized, semi-transparent mesh with visible neural pathways (particle lines tracing across the surface)
- Default state: **green glow** (healthy) with subtle pulse animation
- Background: dark navy/near-black (#0A0E1A) for contrast — professional, futuristic feel

### Click Interaction: Neural Synapse Expansion
- Clicking the brain triggers nodes to **burst outward** from the brain surface and arrange in an orbital pattern around it
- Each node represents a knowledge graph element (e.g., "Firewall", "API Gateway", "Database", "Auth Service", "Load Balancer", "DNS")
- Nodes connected by animated glowing lines (synapses) back to the brain
- Clicking a node shows a small floating tooltip/card with its name, status, and a brief description
- Clicking the brain again collapses nodes back in

### Attack Simulation (Auto-Demo)
- Every ~15 seconds, an auto-attack triggers:
  1. Brain transitions from **green → red** with a ripple/pulse effect
  2. Affected node(s) flash red with a warning indicator
  3. After ~3 seconds, the system "self-heals" — brain fades back to green
  4. A small toast notification shows "Threat detected → Mitigated"
- Smooth color transitions using shader-based glow or emissive material changes

### Minimal Metrics (Floating Around Brain)
- 4 small glass-morphism stat cards positioned at the corners of the viewport:
  - **Threats Blocked**: Counter that increments with each auto-attack
  - **System Uptime**: "99.97%" with a green dot
  - **Response Time**: "< 12ms" 
  - **Active Nodes**: "6/6 Online"
- Cards use subtle backdrop blur, thin borders, light text on dark background

### Top Navigation Bar
- Clean minimal nav: Logo/brand name on the left ("AEGIS" or similar placeholder), minimal links on the right
- Semi-transparent background that doesn't distract from the brain

### Design System
- **Background**: Dark theme (#0A0E1A)
- **Primary accent**: #1978E5 (blue)
- **Healthy state**: #22C55E (green glow)
- **Attack state**: #EF4444 (red glow)
- **Typography**: Inter — clean, minimal labels
- **Cards**: Glass-morphism with 8px border-radius, subtle white borders at 10% opacity

### Tech Stack
- React Three Fiber for 3D brain
- Drei helpers for orbit controls, glow effects, particles
- Tailwind CSS for layout/metrics cards
- React state for attack simulation cycle

