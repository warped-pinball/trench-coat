'''
Warped Pinball main - added to mpremote
to make the pc re-programmer via USB

for Vector, system 11, system 9 etc
'''
import tkinter as tk
from tkinter import ttk, scrolledtext
import sys
import os
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
        print(f"   Deleted: {path}")
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
            print("ITM: ",full_path)
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


        #for now directories must exist...
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




def erase_and_program():
    """Perform the custom sequence of operations using mpremote."""
    #from mpremote.main import State

    state = State()

    try:
        # 1. Connect to the device.
        print("Connecting to the device...")
        do_connect(state, argparse.Namespace(device=["auto"]))
        root.update() 


        # 2. Execute a script on the device.
        print("Executing a script on the device...")
        do_exec(state, argparse.Namespace(expr=["print('Hello from the custom app!')"], follow=True))

        #print("----files 1")
        #list_files(state)
        #print("----files 2")
        #list_files(state,"GameDefs")

        print("\nFIND ALL and DELETE")
        find_all(state)
        print("\nFIND ALL DONE\n")

        # 3. Copy a file to the device.
        print("Uploading a files...")
        #do_filesystem(
        #    state,
        #    argparse.Namespace(command=["cp"], path=["example.py", ":/example.py"], recursive=False, force=False, verbose=True)
        #)
        upload_to_pico(state, "PICO_CODE")


        # 4. List files on the device.
        #print("Listing files...")
        #do_filesystem(state, argparse.Namespace(command=["ls"], path=[], recursive=False, force=False, verbose=False))

        # 5. Disconnect from the device.
        print("Disconnecting...")
        do_disconnect(state)

        print("Finished.")

    except Exception as e:
        print(f"Error occurred: {e}")
        sys.exit(1)

#if __name__ == "__main__":
#    erase_and_program()



# Logging Function
def log_message(log_box, message):
    """Log a message to the scrolling text box."""
    log_box.insert(tk.END, message + "\n")
    log_box.see(tk.END)
    print(message)  # Optionally also log to the console

# GUI Application
def run_gui():
    def run_erase_and_program():
        """Run erase_and_program and redirect output to the log box."""
        try:
            log_message(log_box, "Starting erase and program process...")
            state = State()
            root.update()  # Force GUI update

            # Connect to the device
            log_message(log_box, "Connecting to the device...")
            do_connect(state, argparse.Namespace(device=["auto"]))
            root.update()  # Force GUI update

            # Execute a script on the device
            log_message(log_box, "Executing a script on the device...")
            do_exec(state, argparse.Namespace(expr=["print('Hello from the custom app!')"], follow=True))

            # Delete unnecessary files
            log_message(log_box, "\nFinding and deleting unnecessary files...")
            find_all(state)
            root.update()  # Force GUI update

            # Upload files to the Pico
            #log_message(log_box, "\nUploading files...")
            #root.update()  # Force GUI update
            #upload_to_pico(state, "PICO_CODE")


            dir = "PICO_CODE"
            if os.path.exists(dir) and os.path.isdir(dir):
                log_message(log_box, "\nUploading files...")
                root.update()  # Force GUI update
                upload_to_pico(state, dir)
            else:
                log_message(log_box, f"\nError: Directory {dir} does not exist.")
                root.update()  # Force GUI update


            # Disconnect from the device
            log_message(log_box, "\nDisconnecting...")
            do_disconnect(state)

            log_message(log_box, "Finished.")
        except Exception as e:
            log_message(log_box, f"Error occurred: {e}")
        finally:
            log_message(log_box, "Process complete.")

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
