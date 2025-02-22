import discord
import json
from brook import Brook
from bot_helper import send_message, get_user_input, write_json, get_reputation, change_reputation
from ollama_handler import ask_ollama
import emoji
import importlib
import inspect
import os

# # Rate limiting system
# message_timestamps = []
# self_destruct = False
# async def log_message(message):
#     if self_destruct: return

#     # Keep track of message timestamps
#     current_time = time.time()
#     message_timestamps.append(current_time)
    
#     # Remove timestamps older than 5 seconds
#     while message_timestamps and message_timestamps[0] < current_time - 5:
#         message_timestamps.pop(0)
    
#     # Check if we've sent more than 5 messages in 5 seconds
#     if len(message_timestamps) > 5:
#         self_destruct = True
#         print("Rate limit exceeded. Shutting down bot.")
#         await message.channel.send("TOO MANY MESSAGES INITIATING SELF-DESTRUCT SEQUENCE")
#         await message.channel.send("5")
#         await message.channel.send("4")
#         await message.channel.send("3")
#         await message.channel.send("2")
#         await message.channel.send("1")
#         await message.channel.send("https://tenor.com/bko4E.gif")
#         await client.close()
#         return

# Get functions to bind to commands
def get_command_functions():
    folder = "commands"
    functions = {}

    for filename in os.listdir(folder):
        if filename.endswith('.py') and filename != '__init__.py':
            module_name = f"{folder}.{filename[:-3]}"
            module = importlib.import_module(module_name)

            for name, obj in inspect.getmembers(module):
                if inspect.isfunction(obj):
                    functions[name] = obj
    
    return functions

command_functions = get_command_functions()

# command_functions = {
#     'newinterjection': new_interjection,
#     'newcommand': new_command,
#     'addinterjection': new_interjection,
#     'addcommand': new_command,
#     'beer': beer,
#     'net': net_command,
#     'help': help,
#     'reputation': command_reputation,
#     'interjections': list_interjections,
#     'optout': opt_out,
#     'optin': opt_in,
#     'remove': remove_command_or_interjection,
#     'pay': pay_command,
#     'newmarket': new_market,
#     'addmarket': new_market,
#     'viewmarkets': view_markets,
#     'marketbuy': market_buy,
#     'marketresolve': market_resolve,
#     'markov': markov,
#     'markovchat': markov_chat,
#     'react': react,
# }

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
intents.typing = True

client = discord.Client(intents=intents)

# Define event handlers

transport_channel = None  # This needs to be set after client is ready
@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    global transport_channel
    transport_channel = client.get_channel(1322717023351865395)
    global brook
    brook = Brook(transport_channel, client)

    

async def interject(data):
    msg = data['msg']
    # Load interjections list
    with open('behavior.json', 'r') as file:
        interjections = json.load(file)['interjections']
    
    # Track matching interjections
    matching_interjections = []

    # Go through every interjection
    for _, interjection in interjections.items():
        # Skip if user reputation is out of range
        reputation = get_reputation(msg.author)
        if reputation < interjection['reputation_range'][0]-1 or reputation > interjection['reputation_range'][1]-1:
            continue
        
        whole_message = interjection['whole_message']

        for prompt in interjection['prompts']:
            # Convert message to lowercase
            message_lower = msg.content.lower()
            prompt_lower = prompt.lower()

            # Check if prompt matches message based on whole_message setting
            # Create a version of the message where non-letters are removed
            def clean_text(text):
                # Preserve mentions but clean other parts
                words = []
                current_word = ''
                i = 0
                while i < len(text):
                    if text[i].isalpha():
                        current_word += text[i]
                    else:
                        if current_word:
                            words.append(current_word)
                            current_word = ''
                    i += 1
                if current_word:
                    words.append(current_word)
                return words

            message_words = clean_text(message_lower)
            prompt_words = clean_text(prompt_lower)

            # Continue if prompt_words is empty
            if not prompt_words:
                continue
            
            if whole_message:
            # Check if both message and prompt have same words
                matches = message_words == prompt_words
            else:
                # Check if prompt words appear as a consecutive sequence in message words
                if len(prompt_words) > len(message_words):
                    matches = False
                else:
                    matches = any(prompt_words == message_words[i:i+len(prompt_words)]
                        for i in range(len(message_words) - len(prompt_words) + 1))

            if matches:
                matching_interjections.append((prompt, interjection))

    # If we found matches, respond to the one with the longest prompt
    if matching_interjections:
        longest_prompt, chosen_interjection = max(matching_interjections, key=lambda x: len(x[0]))
        print(f"Interjection caused by {msg.content} by user {msg.author}")
        change_reputation(msg.author, chosen_interjection['reputation_change'])
        await send_message(data, chosen_interjection['response'])

async def run_command(data):
    msg = data['msg']
    # Return if not a command
    if not msg.content.startswith('!'):
        return False
    
    print(f"Command {msg.content} by user {msg.author}")
    
    # Get full command string without the ! prefix
    full_command = msg.content[1:].strip()
    
    # Load commands list
    with open('behavior.json', 'r') as file:
        commands = json.load(file)['commands']

    # Find the longest matching command
    command_name = None
    for cmd in commands:
        if full_command.lower().startswith(cmd.lower()):
            # Update if this is the longest matching command so far
            if command_name is None or len(cmd) > len(command_name):
                command_name = cmd

    # Check if command exists
    if command_name is None:
        await send_message(data, 'Command not found.')
        return True

    # Get the input parameter (everything after the command)
    input_param = full_command[len(command_name):].strip()

    # Execute command
    command = commands[command_name]
    if command['type'] == 'message':
        response = command['response']
        if '{}' in response:
            response = response.replace('{}', input_param)
        await send_message(data, response)
    elif command['type'] == 'function':
        try:
            await command_functions[command_name](data)
        except KeyError:
            await send_message(data, 'Interrobang screwed up and forgot to bind this function. Or the keyerror is some unrelated bug.')
            await send_message(data, command['response'])
    
    return True

last_reaction = "🤪"

@client.event
async def on_message(msg):
    global last_reaction
    # Ignore messages from the bot itself
    if msg.author.id == client.user.id:
        return
    
    data = {'msg': msg, 'client': client, 'brook': brook}
    
    await brook.on_message(msg)

    if 'dimmy' in msg.content.lower() or 'widderkins' in msg.content.lower() or '<@1330727173115613304>' in msg.content.lower():
        # Ollama processing
        response = await ask_ollama(msg.content, last_reaction)
        print(f"Ollama response: {response}")
        response = response.strip()[0]
        if response in emoji.EMOJI_DATA:
            last_reaction = response
            #await msg.add_reaction('<:upvote:1309965553770954914>')
            await msg.add_reaction(response)

    command_found = await run_command(data) # Run command if possible

    if not command_found and msg.reference and msg.reference.resolved and msg.reference.resolved.author == client.user:
        await markov_chat(data)
        return
    
    # Interject if possible
    if not command_found: 
        await interject(data)

# Delete on trash emoji
@client.event
async def on_reaction_add(reaction, user):
    # Check if the reaction is the specific emoji and the message was written by the bot
    if reaction.emoji == '🗑️' and reaction.message.author == client.user:
        await reaction.message.delete()

if __name__ == '__main__':
    with open(r"/home/interrobang/VALUABLE/dimmy_widderkins_token.txt", 'r') as file:
        client.run(file.read())

