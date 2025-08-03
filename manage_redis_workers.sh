#!/bin/bash

# Redis Workers Management Script

WORKERS_SCRIPT="start_redis_workers.py"
LOG_FILE="redis_workers.log"
OUTPUT_FILE="redis_workers.out"

case "$1" in
    start)
        echo "🔄 Starting Redis workers..."
        source venv/bin/activate
        nohup python $WORKERS_SCRIPT > $OUTPUT_FILE 2>&1 &
        echo "✅ Redis workers started in background"
        echo "📋 Process ID: $!"
        echo "📄 Log file: $LOG_FILE"
        echo "📄 Output file: $OUTPUT_FILE"
        ;;
    stop)
        echo "🛑 Stopping Redis workers..."
        pkill -f $WORKERS_SCRIPT
        echo "✅ Redis workers stopped"
        ;;
    restart)
        echo "🔄 Restarting Redis workers..."
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        echo "📊 Redis Workers Status:"
        echo "=========================="
        
        # Check if workers are running
        WORKERS_PID=$(pgrep -f $WORKERS_SCRIPT)
        if [ -n "$WORKERS_PID" ]; then
            echo "✅ Redis workers are running (PID: $WORKERS_PID)"
        else
            echo "❌ Redis workers are not running"
        fi
        
        # Check Redis server
        REDIS_PID=$(pgrep redis-server)
        if [ -n "$REDIS_PID" ]; then
            echo "✅ Redis server is running (PID: $REDIS_PID)"
        else
            echo "❌ Redis server is not running"
        fi
        
        # Show recent log entries
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "📄 Recent log entries:"
            tail -5 $LOG_FILE 2>/dev/null || echo "No log entries found"
        fi
        
        # Show queue status with enhanced task information
        echo ""
        echo "📋 Queue status and task statistics:"
        source venv/bin/activate
        python check_redis.py
        ;;
    logs)
        if [ -f "$LOG_FILE" ]; then
            echo "📄 Redis workers log:"
            tail -20 $LOG_FILE
        else
            echo "❌ Log file not found: $LOG_FILE"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start Redis workers in background"
        echo "  stop    - Stop Redis workers"
        echo "  restart - Restart Redis workers"
        echo "  status  - Show Redis workers status and task statistics"
        echo "  logs    - Show recent log entries"
        exit 1
        ;;
esac 