# In WSL — everything from scratch:
bash SETUP.sh setup      # first-time install
bash SETUP.sh run        # API on :9000
bash SETUP.sh dashboard  # React on :3000
bash SETUP.sh locust     # Locust on :8089
bash SETUP.sh all        # everything in background
bash SETUP.sh status     # health check (just tested)
bash SETUP.sh stop       # kill all