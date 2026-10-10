from src.config import ORIG_COLUMNS_32, PERF_COLUMNS_32
import glob

def main():
    orig_file = glob.glob("data/sample_orig_*.txt")[0]
    perf_file = glob.glob("data/sample_perf_*.txt")[0]
    
    with open(orig_file, "r") as f:
        line = f.readline().strip()
        fields = line.split("|")
        print(f"Origination ({orig_file}): {len(fields)} fields in file, {len(ORIG_COLUMNS_32)} fields in config mapping.")
        if len(fields) != len(ORIG_COLUMNS_32):
            print("WARNING: Origination schema mismatch!")
        
    with open(perf_file, "r") as f:
        line = f.readline().strip()
        fields = line.split("|")
        print(f"Performance ({perf_file}): {len(fields)} fields in file, {len(PERF_COLUMNS_32)} fields in config mapping.")
        if len(fields) != len(PERF_COLUMNS_32):
            print("WARNING: Performance schema mismatch!")

if __name__ == "__main__":
    main()
