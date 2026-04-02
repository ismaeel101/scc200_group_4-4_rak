stop_points = [
    {"name": "a", "heuristic": 1, "connections": []},
    {"name": "b", "heuristic": 1, "connections": []},
    {"name": "c", "heuristic": 1, "connections": []},
    {"name": "d", "heuristic": 1, "connections": []},
    {"name": "e", "heuristic": 1, "connections": []},
    {"name": "f", "heuristic": 1, "connections": []},
]



def calculate_heuristic(stops):
    # Returns a heuristic value based on iterative stops
    # stops is an array of stop points
    total = 0
    for i in range(0, len(stops)):
        total += stops[i]["heuristic"]
    return total

def retrieve_stops(source, destination):
    # This function retrieves the stop points from the data source
    # and returns them in a structured format.
    # will return an array of stop points, and their heuristic values

    # Using calculate_heuristic() between each step, and then A* algorithm to find best route
    
    # Here will be the A* algorithm implementation to find the path from source to destination
    return stop_points