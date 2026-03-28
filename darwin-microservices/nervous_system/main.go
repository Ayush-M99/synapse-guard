package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"github.com/nats-io/nats.go"
)

// NerveAlert matches the Python agent alert format
type NerveAlert struct {
	Service    string  `json:"service"`
	Metric     string  `json:"metric"`
	Value      float64 `json:"value"`
	CusumScore float64 `json:"cusum_score"`
	Timestamp  float64 `json:"timestamp"`
	StrandID   string  `json:"strand_id,omitempty"`
}

// BrainEvent for publishing to brain.update
type BrainEvent struct {
	Event     string  `json:"event"`
	Service   string  `json:"service"`
	Metric    string  `json:"metric,omitempty"`
	Score     float64 `json:"cusum_score,omitempty"`
	Timestamp float64 `json:"timestamp"`
}

func main() {
	natsURL := os.Getenv("NATS_URL")
	if natsURL == "" {
		natsURL = nats.DefaultURL
	}

	// Configurable threshold (default 10.0, §14)
	thresholdStr := os.Getenv("REFLEX_THRESHOLD")
	threshold := 10.0
	if thresholdStr != "" {
		if val, err := strconv.ParseFloat(thresholdStr, 64); err == nil {
			threshold = val
		}
	}

	nc, err := nats.Connect(natsURL,
		nats.Name("darwin-nervous-system"),
		nats.ReconnectWait(nats.DefaultReconnectWait),
		nats.MaxReconnects(-1),
	)
	if err != nil {
		log.Fatalf("Error connecting to NATS: %v", err)
	}
	defer nc.Close()

	fmt.Printf("[NERVOUS SYSTEM] Connected to NATS: %s (threshold: %.1f)\n", natsURL, threshold)

	// Subscribe to all nerve alerts (nerve.*.alert)
	_, err = nc.Subscribe("nerve.*.alert", func(msg *nats.Msg) {
		var alert NerveAlert
		if err := json.Unmarshal(msg.Data, &alert); err != nil {
			log.Printf("Error decoding alert: %v", err)
			return
		}

		fmt.Printf("[REFLEX] %s alerting on %s (Score: %.2f)\n",
			alert.Service, alert.Metric, alert.CusumScore)

		// High-score → Emergency Reflex (configurable threshold)
		if alert.CusumScore > threshold {
			fmt.Printf("  [!] EXTREME SIGNAL — TRIGGERING EMERGENCY ISOLATION REFLEX\n")
			reflexPayload := map[string]interface{}{
				"service":    alert.Service,
				"action":     "fast_isolation",
				"reason":     fmt.Sprintf("Extreme CUSUM score: %.2f", alert.CusumScore),
				"cusum_score": alert.CusumScore,
			}
			data, _ := json.Marshal(reflexPayload)
			nc.Publish("antibody.reflex.trigger", data)
		}

		// Forward to brain.update for dashboard (§12)
		brainEvent := BrainEvent{
			Event:     "nerve_alert",
			Service:   alert.Service,
			Metric:    alert.Metric,
			Score:     alert.CusumScore,
			Timestamp: alert.Timestamp,
		}
		eventData, _ := json.Marshal(brainEvent)
		nc.Publish("brain.update", eventData)

		// Forward to decision engine
		nc.Publish("antibody.discovery.queue", msg.Data)
	})
	if err != nil {
		log.Fatalf("Error subscribing: %v", err)
	}

	// Also subscribe to virus events for logging
	nc.Subscribe("virus.inject", func(msg *nats.Msg) {
		fmt.Printf("[NERVOUS SYSTEM] Virus injection detected: %s\n", string(msg.Data))
	})

	nc.Subscribe("virus.generation.event", func(msg *nats.Msg) {
		fmt.Printf("[NERVOUS SYSTEM] Virus generation event: %s\n", string(msg.Data))
	})

	fmt.Printf("[NERVOUS SYSTEM] Wired to nerve.*.alert. Waiting for nerve impulses...\n")

	// Keep running
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs

	fmt.Println("[NERVOUS SYSTEM] Shutting down...")
}
