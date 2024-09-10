import tkinter as tk
import BSSID
import numpy as np
import ast
from PIL import Image, ImageTk
from tkinter import filedialog, ttk
from scipy.ndimage import gaussian_filter
import matplotlib.pyplot as plt

# Function to handle left click event
def LeftClick(event):
    try:
        SSID = ast.literal_eval(ssid_dropdown.get())
    except (ValueError, SyntaxError):
        tk.messagebox.showerror(title="ERROR", message="Select an SSID")
    z = BSSID.ssid_signal(SSID["SSID"])
    for i in range(-3, 3):
        for i in range(-3, 3):
            x = event.x + i
            y = event.y + i
            print(x, y, z)
            result = {"X": x,"Y": y,"Z": z}
            results.append(result)

def open_map():
    # Open file dialog to select an image
    file_path = filedialog.askopenfilename(filetypes=[("JPEG Files", "*.jpg;*.jpeg")])

    # Check if a file was selected
    if file_path:
        # Open the image file
        global image
        image = Image.open(file_path)
        
        # Convert the image to Tkinter-compatible format
        global image_tk
        image_tk = ImageTk.PhotoImage(image)
        
        # Create a canvas to display the image
        map = tk.Canvas(mainframe, width=image.width, height=image.height)
        map.create_image(0, 0, anchor=tk.NW, image=image_tk)
        map.image = image_tk
        map.grid(column=0, row=1)
        map.bind("<Button-1>", LeftClick)

def saveResult():
    # Save the results to a file
    file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
    if file_path:
        with open(file_path, "w") as file:
            file.write(str(results))

def loadResult():
    # Load the results from a file
    file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
    if file_path:
        with open(file_path, "r") as file:
            results.extend(ast.literal_eval(file.read()))

def showResult():
    resultsWindow = tk.Toplevel(mapper)
    resultsWindow.title("Results")
    resultsWindow.geometry("300x300")
    resultsLabel = tk.Label(resultsWindow, text=results, wraplength=300)
    print(results)
    resultsLabel.pack()

def clearResult():
    confirmClearResult = tk.messagebox.askyesno(title="Clear Results", message="Are you sure you want to clear the results?")
    if confirmClearResult:
        results.clear()
    else:
        pass

def processResult():
    # Create a new window to display the results
    resultsWindow = tk.Toplevel(mapper)
    resultsWindow.title("Results")
    resultsWindow.geometry("300x300")
    resultsLabel = tk.Label(resultsWindow, text=results, wraplength=300)
    resultsLabel.pack()

    # Extract the X, Y, and Z values from the results
    x = np.array([result["X"] for result in results])
    y = np.array([result["Y"] for result in results])
    z = np.array([int(result["Z"][0]["Signal"].replace("%", "")) for result in results])
    # Create a grid of the same dimensions as the image
    grid = np.full((image.height, image.width), np.average(z))
    # Assign the signal strength values to the corresponding grid cells
    for i in range(len(x)):
        grid[y[i], x[i]] = z[i]

    # Smooth the grid using a Gaussian filter
    smoothed_grid = gaussian_filter(grid, sigma=30)

    # Plot the heatmap
    plt.imshow(smoothed_grid, cmap='plasma' , interpolation='nearest')
    plt.show()
    #x, y = np.meshgrid(x, y)


# vairables
results = []

# Create the main window
mapper = tk.Tk()
mainframe = tk.Frame(mapper)
mapper.title("Wi-Fi Heatmapper")
mainframe.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
mainframe.columnconfigure(0, weight=1)
mainframe.rowconfigure(0, weight=1)

# Create a dropdown to select SSID
ssid_var = tk.StringVar()
list_of_ssids = BSSID.network_list()
ssid_dropdown = ttk.Combobox(
    mainframe,
    textvariable=ssid_var,
    values=list_of_ssids,
    )
ssid_dropdown.grid(column=0, row=0, sticky=tk.W)
ssid_dropdown.current(0)

# Create a menu bar
menubar = tk.Menu(mapper)
# Create a file menu
filemenu = tk.Menu(menubar, tearoff=0)
filemenu.add_command(label="Open Map", command=open_map)
filemenu.add_command(label="Save Results", command=saveResult)
filemenu.add_command(label="Load Results", command=loadResult)
filemenu.add_separator()
filemenu.add_command(label="Exit", command=mapper.quit)
menubar.add_cascade(label="File", menu=filemenu)
processingmenu = tk.Menu(menubar, tearoff=0)
processingmenu.add_command(label="Process Results", command=processResult)
processingmenu.add_command(label="Show Results", command=showResult)
processingmenu.add_separator()
processingmenu.add_command(label="Clear Results", command=clearResult)
menubar.add_cascade(label="Processing", menu=processingmenu)

mapper.config(menu=menubar)
mapper.mainloop()
