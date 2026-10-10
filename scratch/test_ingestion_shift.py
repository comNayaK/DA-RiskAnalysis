import subprocess

def test_ingestion():
    with open('output/ingestion_test_results.txt', 'w') as f:
        def log(msg):
            print(msg)
            f.write(msg + '\n')
            
        log("=== Positive Case (sample_orig_2014.txt) ===")
        line_2014 = subprocess.check_output("head -1 data/sample_orig_2014.txt", shell=True).decode().strip().split('|')
        loan_id = line_2014[19]
        loan_term = line_2014[21]
        log(f"loan_id: {loan_id}, loan_term (field after): {loan_term}")
        
        try:
            assert len(loan_id) == 12 and loan_id.startswith('F')
            assert loan_term.isdigit()
            log("Positive assertions PASSED.")
        except AssertionError as e:
            log(f"Positive assertions FAILED: {e}")
            
        log("\n=== Negative Case (Constructed shifting error) ===")
        # We simulate a missing field before loan_id, causing loan_id to be at index 18 and loan_term at index 20
        # The shifted row will have loan_id where loan_term should be, or vice versa
        shifted_row = line_2014[:18] + line_2014[19:]
        shifted_loan_id = shifted_row[19]
        shifted_loan_term = shifted_row[21]
        log(f"Shifted loan_id: {shifted_loan_id}, Shifted loan_term: {shifted_loan_term}")
        
        try:
            assert len(shifted_loan_id) == 12 and shifted_loan_id.startswith('F')
            assert shifted_loan_term.isdigit()
            log("Negative assertions PASSED.")
        except AssertionError as e:
            log("Negative assertions CORRECTLY FAILED: AssertionError caught due to mid-row shift.")

if __name__ == "__main__":
    test_ingestion()
