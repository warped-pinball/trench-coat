'''
Warped Pinball main - added to mpremote
to make the pc re-programmer via USB

for Vector, system 11, system 9 etc
'''
import tkinter as tk
from tkinter import ttk, scrolledtext
import sys
import os
import io
import argparse
from mpremote.commands import do_connect, do_exec, do_filesystem, do_disconnect
from mpremote.main import State

#list files that should NOT be deleted here - must include directory name if file is in a sub directory
exceptions = { "GameDefs/Game_Definition.json" }


def delete_path(state,path):
    """Delete a file or directory."""
    try:
        cmd_args = argparse.Namespace(command=["rm"], path=[path], recursive=True, force=False, verbose=False)
        do_filesystem(state, cmd_args)
        print(f"Del: {path}")        
    except Exception as e:
        print(f"   Error deleting {path}: {e}")


def list_files(state,path=""):
    """List files and directories in the given path."""
    output = []
    try:
        cmd_args = argparse.Namespace(command=["ls"], path=[path], recursive=False, force=False, verbose=False)
        captured_output = do_filesystem(state, cmd_args)
        #print("pth",path,"output start",captured_output)  #output is size and file name
        if captured_output:
            # Parse the output and extract file/directory names
            for line in captured_output.splitlines():
                parts = line.split()
                if len(parts) > 0:
                    output.append(parts[-1])  # The last part is the file/directory name
    except Exception as e:
        print(f"Error listing files in {path}: {e}")
    return output


#Find all and  DELETE!
def find_all(state):
  # Start at the root directory.
    paths_to_check = [""]
    while paths_to_check:
        print("paths",paths_to_check)
        current_path = paths_to_check.pop()
        items = list_files(state,current_path)  # file name. directories name ends in "/""
        for item in items:
            full_path = f"{current_path}{item}" if current_path else item
            #print("ITM: ",full_path)
            if full_path in exceptions:
                print(f"Skipping: {full_path}")
            elif item.endswith("/"):  # Directory
                print("DIRECTORY: ",full_path)
                paths_to_check.append(full_path)
            else:  # File
                delete_path(state,full_path)




def upload_to_pico(state, local_dir, pico_dir=""):
  
    for root, dirs, files in os.walk(local_dir):
        # Calculate the relative path from the base directory
        relative_path = os.path.relpath(root, local_dir)
        # Construct the corresponding target path on the Pico
        target_dir = os.path.join(pico_dir, relative_path).replace("\\", "/")

        #for now directories must exist. In the future create them? need to check if they exist first to avoid errors
        '''
        # Create the corresponding directory on the Pico
        if relative_path != ".":
            print(f"Creating directory: {target_dir}")
            do_filesystem(
                state,
                argparse.Namespace(command=["mkdir"], path=[f":{target_dir}"], recursive=False, force=False, verbose=True),
            )
        '''

        # Upload each file in the current directory
        for file_name in files:
            local_file = os.path.join(root, file_name)
            pico_file = os.path.join(target_dir, file_name).replace("\\", "/")
            print(f"Uploading {local_file} to {pico_file}")
            do_filesystem(
                state,
                argparse.Namespace(command=["cp"], path=[local_file, f":{pico_file}"], recursive=False, force=False, verbose=True),
            )


#capture stdio output from mpremote functions as needed to place in window text box
def capture_output(func, *args, **kwargs):   
    old_stdout = sys.stdout  # Save the current stdout
    sys.stdout = io.StringIO()  # Redirect stdout to a StringIO object
    try:
        func(*args, **kwargs)  # Execute the function
        return sys.stdout.getvalue()  # Get the output
    finally:
        sys.stdout = old_stdout  # Restore the original stdout


# Logging Function
def log_message(log_box, message):
    """Log a message to the scrolling text box."""
    log_box.insert(tk.END, message + "\n")
    log_box.see(tk.END)
    print(message)  

class LogBoxWriter:
    def __init__(self, log_box, root):
        self.log_box = log_box
        self.root = root
        self.encoding = "utf-8"  # Encoding for compatibility

    def write(self, message):
        """Write a message to the log box and update the GUI."""
        if message.strip():  # Ignore empty messages
            self.log_box.insert(tk.END, message + "\n")
            self.log_box.see(tk.END)  # Auto-scroll
            self.root.update()  # Force GUI update

    def flush(self):
        """Flush the writer (required for sys.stdout compatibility)."""
        pass

    def isatty(self):
        """Return False to indicate this is not a TTY (required for sys.stdout compatibility)."""
        return False



# GUI Application
def run_gui():
    def run_erase_and_program():        
        try:
            # Redirect sys.stdout to LogBoxWriter
            original_stdout = sys.stdout
            sys.stdout = LogBoxWriter(log_box, root)

            print("Starting erase and program process...")
            state = State()

            # Connect to the device
            print("Connecting to the device...")
            do_connect(state, argparse.Namespace(device=["auto"]))

            # Execute a script on the device
            #print("Executing a script on the device...")
            #do_exec(state, argparse.Namespace(expr=["print('Hello from the custom app!')"], follow=True))

            # Delete unnecessary files
            print("\nFinding and deleting unnecessary files...")
            find_all(state)

            # Upload files to the Pico
            print("\nUploading files...")
            upload_to_pico(state, "PICO_CODE")

            # Disconnect from the device
            print("\nDisconnecting...")
            do_disconnect(state)

            print("Finished.")
        except Exception as e:
            print(f"Error occurred: {e}")
        finally:
            # Restore original stdout
            sys.stdout = original_stdout
            print("Process complete.")


    # Create the main window
    root = tk.Tk()
    root.title("Warped Pinball Programmer")
    root.geometry("600x500")

    # Title and Version
    title_label = tk.Label(root, text="Warped Pinball Programmer", font=("Helvetica", 16))
    title_label.pack(pady=10)

    version_label = tk.Label(root, text="Version 0.00.01", font=("Helvetica", 12))
    version_label.pack(pady=5)

    # Logo
    logo_path = "logo.png"  # Replace with your logo file
    if os.path.exists(logo_path):
        logo_image = tk.PhotoImage(file=logo_path)
        logo_label = tk.Label(root, image=logo_image)
        logo_label.image = logo_image  # Keep a reference to avoid garbage collection
        logo_label.pack(pady=10)

    # Scrolling Text Box
    log_box = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=70, height=10, font=("Courier", 10))
    log_box.pack(pady=10, padx=10)

    # Program Button
    program_button = ttk.Button(root, text="Program!", command=run_erase_and_program)
    program_button.pack(pady=20)

    # Start the GUI event loop
    root.mainloop()

# Run the GUI
if __name__ == "__main__":
    run_gui()
