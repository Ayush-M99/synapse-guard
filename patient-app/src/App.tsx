import { useState, useEffect } from 'react';
import { ShoppingCart, Package, CreditCard, ShieldAlert, Activity, CheckCircle, Bell } from 'lucide-react';

export default function PatientApp() {
  const [logs, setLogs] = useState<string[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [latency, setLatency] = useState(0);

  const addLog = (msg: string) => setLogs(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev].slice(0, 10));

  const simulatePurchase = async () => {
    setIsProcessing(true);
    addLog('🛒 Initiating purchase workflow...');
    const startTime = Date.now();

    try {
      // 1. Authenticate (Auth Service)
      addLog('🔐 Checking Auth Service...');
      await fetch('http://localhost:8000/api/auth/login', { method: 'POST', body: JSON.stringify({ user: "test" }) });

      // 2. Check Inventory (Inventory Service)
      addLog('📦 Verifying Inventory Service...');
      await fetch('http://localhost:8000/api/inventory/check');

      // 3. Process Payment (Payment Service)
      addLog('💳 Charging Payment Service...');
      await fetch('http://localhost:8000/api/payment/charge', { method: 'POST', body: JSON.stringify({ amount: 99.99 }) });

      // 4. Send Notification (Notification Service)
      addLog('🔔 Dispatching Notification...');
      await fetch('http://localhost:8000/api/notification/send', { method: 'POST', body: JSON.stringify({ msg: "Success" }) });

      const finalLatency = Date.now() - startTime;
      setLatency(finalLatency);
      addLog(`✅ Purchase Complete! Total time: ${finalLatency}ms`);

    } catch (e) {
      addLog(`❌ ERROR: Network failure or Gateway Timeout: ${e.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-900 text-white p-8 font-sans">
      <div className="max-w-4xl mx-auto space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-800 pb-6">
          <div className="flex items-center space-x-4">
            <div className="p-3 bg-blue-500/20 rounded-xl">
              <Package className="w-8 h-8 text-blue-400" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">TechStore E-Commerce</h1>
              <p className="text-neutral-400">Application Under Test ("The Patient")</p>
            </div>
          </div>
          <div className="flex items-center space-x-2 px-4 py-2 bg-neutral-800 rounded-lg">
            <Activity className="w-5 h-5 text-green-400" />
            <span className="font-mono">{latency > 0 ? `${latency}ms` : 'Idle'}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Storefront Panel */}
          <div className="bg-neutral-800/50 border border-neutral-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold mb-6 flex items-center">
              <ShoppingCart className="w-5 h-5 mr-3 text-neutral-400" />
              Demo Product
            </h2>

            <div className="bg-neutral-900 rounded-xl p-6 mb-6">
              <h3 className="text-2xl font-bold mb-2">Quantum Laptop</h3>
              <p className="text-neutral-400 mb-4">High-performance computing device.</p>
              <div className="text-3xl font-mono text-green-400">$2,499.00</div>
            </div>

            <button
              onClick={simulatePurchase}
              disabled={isProcessing}
              className={`w-full py-4 rounded-xl flex items-center justify-center font-bold text-lg transition-all ${isProcessing
                  ? 'bg-blue-600/50 cursor-not-allowed opacity-70'
                  : 'bg-blue-600 hover:bg-blue-500 hover:shadow-[0_0_20px_rgba(37,99,235,0.4)]'
                }`}
            >
              {isProcessing ? (
                <span className="flex items-center animate-pulse">
                  <Activity className="w-5 h-5 mr-2 animate-spin" />
                  Processing...
                </span>
              ) : (
                <span className="flex items-center">
                  <CreditCard className="w-5 h-5 mr-2" />
                  Simulate Purchase (Hit API Gateway)
                </span>
              )}
            </button>
            <p className="text-xs text-neutral-500 mt-4 text-center">
              This triggers: Auth → Inventory → Payment → Notification services.
            </p>
          </div>

          {/* Network Logs Panel */}
          <div className="bg-black/40 border border-neutral-800 rounded-2xl p-6 font-mono text-sm max-h-[400px] overflow-y-auto">
            <h2 className="text-lg font-semibold mb-4 text-neutral-300 flex items-center sticky top-0 bg-black/40 pb-2">
              <ShieldAlert className="w-4 h-4 mr-2" />
              Gateway Network Audit
            </h2>
            <div className="space-y-2">
              {logs.length === 0 ? (
                <div className="text-neutral-600 italic">No network traffic...</div>
              ) : (
                logs.map((log, i) => (
                  <div key={i} className={`pb-1 ${log.includes('❌') ? 'text-red-400' : log.includes('✅') ? 'text-green-400' : 'text-neutral-400'}`}>
                    {log}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
