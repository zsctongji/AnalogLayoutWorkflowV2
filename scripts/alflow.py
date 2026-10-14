from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from analog_layout_workflow.cli import main
raise SystemExit(main())
