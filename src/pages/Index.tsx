import { NavBar } from "@/components/NavBar";
import { MetricCards } from "@/components/MetricCards";
import { StatusBar } from "@/components/StatusBar";
import { SystemStats } from "@/components/SystemStats";
import Spline from "@splinetool/react-spline";

const Index = () => {
  return (
    <div className="relative w-full h-screen overflow-hidden bg-background">
      <NavBar />

      {/* Spline 3D Brain — full viewport background */}
      <div className="absolute inset-0 z-0">
        <Spline scene="https://prod.spline.design/OJxhR7BaxA1JFD8q/scene.splinecode" />
      </div>

      {/* Subtle vignette overlay */}
      <div className="absolute inset-0 z-[1] pointer-events-none bg-gradient-to-b from-background/80 via-transparent to-background/90" />

      {/* Top metrics row */}
      <MetricCards />

      {/* Bottom system stats */}
      <SystemStats />

      {/* Status bar */}
      <StatusBar />
    </div>
  );
};

export default Index;
