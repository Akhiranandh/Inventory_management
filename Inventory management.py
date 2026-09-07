import json
from datetime import datetime
import sqlite3

# List to store all inventory items
inventory = []

def load_inventory():

    global inventory

    try:
        with open("inventory.json", "r") as file:
            inventory = json.load(file)

            if not isinstance(inventory, list):
                inventory = []

    except (FileNotFoundError, json.JSONDecodeError):
        inventory = []


def save_inventory():

    with open("inventory.json", "w") as file:
        json.dump(inventory, file, indent=4)


def add_item():

    item_id = input("Enter Item ID: ")

    # Check whether the Item ID already exists
    for item in inventory:

        if item["item_id"] == item_id:
            print("Item ID already exists!")
            return

    name = input("Enter Item Name: ").strip()

    location = input("Enter Location: ")

    # Validate quantity
    try:

        quantity = int(input("Enter Quantity: "))

        if quantity <= 0:
            print("Quantity must be greater than 0.")
            return

    except ValueError:

        print("Please enter a valid number.")
        return

    # Validate expiry date
    try:

        expiry = input("Enter Expiry Date (DD-MM-YYYY): ")

        datetime.strptime(expiry, "%d-%m-%Y")

    except ValueError:

        print("Please enter a valid date in DD-MM-YYYY format.")
        return

    new_item = {
        "item_id": item_id,
        "name": name,
        "location": location,
        "quantity": quantity,
        "expiry": expiry
    }

    inventory.append(new_item)

    save_inventory()

    print("Item added successfully!")


def view_inventory():

    if len(inventory) == 0:
        print("The list is empty")
        return

    for item in inventory:

        print("Item ID:", item["item_id"])
        print("Name:", item["name"])
        print("Location:", item["location"])
        print("Quantity:", item["quantity"])
        print("Expiry:", item["expiry"])
        print("------------------------")


def search_item():

    item_id = input("Enter the Item ID that you want to search: ")

    for item in inventory:

        if item["item_id"] == item_id:

            print("Item found!")
            print("Item ID:", item["item_id"])
            print("Name:", item["name"])
            print("Location:", item["location"])
            print("Quantity:", item["quantity"])
            print("Expiry:", item["expiry"])

            return

    print("Item not found.")


def update_item():

    item_id = input("Enter the item ID that you want to update: ")

    for item in inventory:

        if item["item_id"] == item_id:

            while True:

                print("\nWhat do you want to edit?")
                print("1. Quantity")
                print("2. Location")
                print("3. Expiry")
                print("4. Name")
                print("5. Exit")

                choice = input("Enter your choice: ")

                if choice == "1":

                    try:

                        new_quantity = int(
                            input("Enter the new quantity: ")
                        )

                        if new_quantity <= 0:
                            print("Quantity must be greater than 0.")
                            continue

                        item["quantity"] = new_quantity

                        save_inventory()

                        print("Quantity updated successfully!")

                    except ValueError:

                        print("Please enter a valid number.")

                elif choice == "2":

                    item["location"] = input(
                        "Enter the new location: "
                    )

                    save_inventory()

                    print("Location updated successfully!")

                elif choice == "3":

                    try:

                        new_expiry = input(
                            "Enter the new expiry date (DD-MM-YYYY): "
                        )

                        datetime.strptime(
                            new_expiry,
                            "%d-%m-%Y"
                        )

                        item["expiry"] = new_expiry

                        save_inventory()

                        print("Expiry updated successfully!")

                    except ValueError:

                        print(
                            "Please enter a valid date in DD-MM-YYYY format."
                        )

                elif choice == "4":

                    item["name"] = input(
                        "Enter the new name: "
                    ).strip()

                    save_inventory()

                    print("Name updated successfully!")

                elif choice == "5":

                    break

                else:

                    print("Invalid choice!")

            return

    print("Item not found.")


def delete_item():

    item_id = input("Enter the Item ID to delete: ")

    for item in inventory:

        if item["item_id"] == item_id:

            inventory.remove(item)

            save_inventory()

            print("Item deleted successfully!")

            return

    print("Item not found.")


# Load inventory when program starts
load_inventory()


while True:

    print("\nMENU")
    print("1. Add Item")
    print("2. View Inventory")
    print("3. Search Item")
    print("4. Update Item")
    print("5. Delete Item")
    print("6. Exit")

    choice = input("Enter your choice: ")

    if choice == "1":

        add_item()

    elif choice == "2":

        view_inventory()

    elif choice == "3":

        search_item()

    elif choice == "4":

        update_item()

    elif choice == "5":

        delete_item()

    elif choice == "6":

        break

    else:

        print("Invalid choice!")