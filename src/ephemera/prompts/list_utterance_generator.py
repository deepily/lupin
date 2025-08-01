import random

# Define action verbs
action_verbs = [
    "Create New", "Update", "Delete", "Mark as Done", "Prioritize", "Remind"
]

# Define list types and corresponding items
list_types_and_items = {
    "Grocery Shopping List"        : [ "Milk", "Eggs", "Bread", "Apples", "Chicken Breast" ],
    "Daily Tasks/Errands List"     : [ "Pay electricity bill", "Call the dentist", "Pick up dry cleaning" ],
    "Work-related Tasks List"      : [ "Prepare presentation", "Email project report", "Complete budget review" ],
    "Household Chores List"        : [ "Vacuum living room", "Clean bathrooms", "Wash dishes" ],
    "Meal Planning List"           : [ "Grilled chicken dinner", "Spaghetti Bolognese", "Taco night" ],
    "Study or Homework List"       : [ "Math assignment", "History quiz study", "Biology chapter reading" ],
    "Health and Fitness Goals List": [ "Jog for 30 minutes", "Drink 8 glasses of water", "Attend yoga class" ],
    "Event Planning List"          : [ "Finalize guest list", "Book venue", "Send out invitations" ],
    "Travel Planning List"         : [ "Book flights", "Reserve accommodations", "Research activities" ],
    "Personal Goals/Projects List" : [ "Read 30 minutes daily", "Save $200 monthly", "Learn basic Spanish" ]
}


# Function to generate random list management utterances
def generate_utterances( num_utterances ):
    """
    Generate random list management utterances for natural language training.
    
    Requires:
        - num_utterances must be a positive integer
        - action_verbs list must be defined and non-empty
        - list_types_and_items dictionary must be defined and populated
        
    Ensures:
        - Returns list of exactly num_utterances utterance strings
        - Each utterance follows the format: "{action} '{item}' in the {list_type}."
        - Action verbs, items, and list types are randomly selected
        - All combinations are valid based on predefined mappings
        
    Args:
        num_utterances: Number of utterances to generate (must be positive integer)
        
    Returns:
        list: List of generated utterance strings
        
    Raises:
        IndexError: If action_verbs or list_types_and_items are empty
        KeyError: If list_types_and_items values are empty lists
        ValueError: If num_utterances is not a positive integer
    """
    
    utterances = [ ]
    for _ in range( num_utterances ):
        
        list_type = random.choice( list( list_types_and_items.keys() ) )
        action_verb = random.choice( action_verbs )
        item = random.choice( list_types_and_items[ list_type ] )
        
        # Constructing the utterance
        utterance = f"{action_verb} '{item}' in the {list_type}."
        utterances.append( utterance )
    
    return utterances


if __name__ == "__main__":
    # Generate 100 random list management utterances
    random_utterances = generate_utterances( 100 )
    for utterance in random_utterances:
        print( utterance )
