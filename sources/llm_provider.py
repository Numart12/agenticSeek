
import os
import time
import ollama
from ollama import chat
import requests
import subprocess
import ipaddress
import httpx
import platform
from dotenv import load_dotenv, set_key
from openai import OpenAI
from huggingface_hub import InferenceClient
from typing import List, Tuple, Type, Dict
from sources.utility import pretty_print, animate_thinking
from sources.logger import Logger

class Provider:
    def __init__(self, provider_name, model, server_address = "127.0.0.1:5000", is_local=False):
        self.provider_name = provider_name.lower()
        self.model = model
        self.is_local = is_local
        self.server_ip = self.check_address_format(server_address)
        self.available_providers = {
            "ollama": self.ollama_fn,
            "server": self.server_fn,
            "openai": self.openai_fn,
            "lm-studio": self.lm_studio_fn,
            "huggingface": self.huggingface_fn,
            "deepseek": self.deepseek_fn,
            "dsk_deepseek": self.dsk_deepseek,
            "test": self.test_fn
        }
        self.logger = Logger("provider.log")
        self.api_key = None
        self.unsafe_providers = ["openai", "deepseek", "dsk_deepseek"]
        if self.provider_name not in self.available_providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        if self.provider_name in self.unsafe_providers:
            pretty_print("Warning: you are using an API provider. You data will be sent to the cloud.", color="warning")
            self.api_key = self.get_api_key(self.provider_name)
        elif self.provider_name != "ollama":
            pretty_print(f"Provider: {provider_name} initialized at {self.server_ip}", color="success")
        self.check_address_format(self.server_ip)
        if not self.is_ip_online(self.server_ip.split(':')[0]):
            raise Exception(f"Server at {self.server_ip} is offline.")

    def get_api_key(self, provider):
        load_dotenv()
        api_key_var = f"{provider.upper()}_API_KEY"
        api_key = os.getenv(api_key_var)
        if not api_key:
            api_key = input(f"Please enter your {provider} API key: ")
            set_key(".env", api_key_var, api_key)
            self.logger.info("Set API key in env.")
            load_dotenv()
        return api_key

    def check_address_format(self, address):
        """
        Validate if the address is valid IP.
        """
        try:
            address = address.replace('http://', '')
            ip, port = address.rsplit(":", 1)
            if all(c.lower() in ".:abcdef0123456789" for c in ip):
                ipaddress.ip_address(ip)
            if not port.isdigit() or not (0 <= int(port) <= 65535):
                raise ValueError("Port must be a number between 0 and 65535.")
        except ValueError as e:
            raise Exception(f"Invalid address format: {e}. Is port specified?")
        return address

    def respond(self, history, verbose = True):
        """
        Use the choosen provider to generate text.
        """
        llm = self.available_providers[self.provider_name]
        self.logger.info(f"Using provider: {self.provider_name} at {self.server_ip}")
        try:
            thought = llm(history, verbose)
        except KeyboardInterrupt:
            self.logger.warning("User interrupted the operation with Ctrl+C")
            return "Operation interrupted by user. REQUEST_EXIT"
        except ConnectionError as e:
            raise ConnectionError(f"{str(e)}\nConnection to {self.server_ip} failed.")
        except AttributeError as e:
            raise NotImplementedError(f"{str(e)}\nIs {self.provider_name} implemented ?")
        except Exception as e:
            if "RemoteDisconnected" in str(e):
                return f"{self.server_ip} seem offline. RemoteDisconnected error."
            raise Exception(f"Provider {self.provider_name} failed: {str(e)}") from e
        return thought

    def is_ip_online(self, ip_address):
        """
        Check if an IP address is online by sending a ping request.
        """
        if ip_address == "127.0.0.1":
            return True
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', ip_address]
        try:
            output = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if output.returncode == 0:
                return True
            else:
                self.logger.error(f"Ping command returned code: {output.returncode}")
                return False
        except subprocess.TimeoutExpired:
            return False
        except Exception as e:
            pretty_print(f"Error with ping request {str(e)}", color="failure")
            return False

    def server_fn(self, history, verbose = False):
        """
        Use a remote server with LLM to generate text.
        """
        thought = ""
        route_setup = f"http://{self.server_ip}/setup"
        route_gen = f"http://{self.server_ip}/generate"

        if not self.is_ip_online(self.server_ip.split(":")[0]):
            raise Exception(f"Server is offline at {self.server_ip}")

        try:
            requests.post(route_setup, json={"model": self.model})
            requests.post(route_gen, json={"messages": history})
            is_complete = False
            while not is_complete:
                response = requests.get(f"http://{self.server_ip}/get_updated_sentence")
                if "error" in response.json():
                    pretty_print(response.json()["error"], color="failure")
                    break
                thought = response.json()["sentence"]
                is_complete = bool(response.json()["is_complete"])
                time.sleep(2)
        except KeyError as e:
            raise Exception(f"{str(e)}\nError occured with server route. Are you using the correct address for the config.ini provider?") from e
        except Exception as e:
            raise e
        return thought


    def ollama_fn(self, history, verbose = False):
        """
        Use local ollama server to generate text.
        """
        thought = ""
        try:
            stream = chat(
                model=self.model,
                messages=history,
                stream=True,
            )
            for chunk in stream:
              if verbose:
                print(chunk['message']['content'], end='', flush=True)
              thought += chunk['message']['content']
        except httpx.ConnectError as e:
            raise Exception("\nOllama connection failed. provider should not be set to ollama if server address is not localhost") from e
        except ollama.ResponseError as e:
            if e.status_code == 404:
                animate_thinking(f"Downloading {self.model}...")
                ollama.pull(self.model)
                self.ollama_fn(history, verbose)
            if "refused" in str(e).lower():
                raise Exception("Ollama connection failed. is the server running ?") from e
            raise e
        return thought
    
    def huggingface_fn(self, history, verbose=False):
        """
        Use huggingface to generate text.
        """
        client = InferenceClient(
        	api_key=self.get_api_key("huggingface")
        )
        completion = client.chat.completions.create(
            model=self.model, 
        	messages=history, 
        	max_tokens=1024,
        )
        thought = completion.choices[0].message
        return thought.content

    def openai_fn(self, history, verbose=False):
        """
        Use openai to generate text.
        """
        base_url = self.server_ip
        if self.is_local:
            client = OpenAI(api_key=self.api_key, base_url=f"http://{base_url}")
        else:
            client = OpenAI(api_key=self.api_key)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=history,
            )
            if response is None:
                raise Exception("OpenAI response is empty.")
            thought = response.choices[0].message.content
            if verbose:
                print(thought)
            return thought
        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}") from e

    def deepseek_fn(self, history, verbose=False):
        """
        Use deepseek api to generate text.
        """
        client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=history,
                stream=False
            )
            thought = response.choices[0].message.content
            if verbose:
                print(thought)
            return thought
        except Exception as e:
            raise Exception(f"Deepseek API error: {str(e)}") from e
    
    def lm_studio_fn(self, history, verbose = False):
        """
        Use local lm-studio server to generate text.
        lm studio use endpoint /v1/chat/completions not /chat/completions like openai
        """
        thought = ""
        route_start = f"http://{self.server_ip}/v1/chat/completions"
        payload = {
            "messages": history,
            "temperature": 0.7,
            "max_tokens": 4096,
            "model": self.model
        }
        if not self.is_ip_online(self.server_ip.split(":")[0]):
            raise Exception(f"Server is offline at {self.server_ip}")
        try:
            response = requests.post(route_start, json=payload)
            result = response.json()
            if verbose:
                print("Response from LM Studio:", result)
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP request failed: {str(e)}") from e
        except Exception as e:
            raise Exception(f"An error occurred: {str(e)}") from e
        return thought

    def dsk_deepseek(self, history, verbose = False):
        """
        Use: xtekky/deepseek4free
        For free api. Api key should be set to DSK_DEEPSEEK_API_KEY
        This is an unofficial provider, you'll have to find how to set it up yourself.
        """
        from dsk.api import (
            DeepSeekAPI, 
            AuthenticationError,
            RateLimitError,
            NetworkError,
            CloudflareError,
            APIError
        )
        thought = ""
        message = '\n---\n'.join([f"{msg['role']}: {msg['content']}" for msg in history])

        try:
            api = DeepSeekAPI(self.api_key)
            chat_id = api.create_chat_session()
            for chunk in api.chat_completion(chat_id, message):
                if chunk['type'] == 'text':
                    thought += chunk['content']
            return thought
        except AuthenticationError:
            raise AuthenticationError("Authentication failed. Please check your token.") from e
        except RateLimitError:
            raise RateLimitError("Rate limit exceeded. Please wait before making more requests.") from e
        except CloudflareError as e:
            raise CloudflareError(f"Cloudflare protection encountered: {str(e)}") from e
        except NetworkError:
            raise NetworkError("Network error occurred. Check your internet connection.") from e
        except APIError as e:
            raise APIError(f"API error occurred: {str(e)}") from e
        return None

    def test_fn(self, history, verbose = True):
        """
        This function is used to conduct tests.
        """
        thought = """
\n\n```json\n{\n  \"plan\": [\n    {\n      \"agent\": \"Web\",\n      \"id\": \"1\",\n      \"need\": null,\n      \"task\": \"Conduct a comprehensive web search to identify at least five AI startups located in Osaka. Use reliable sources and websites such as Crunchbase, TechCrunch, or local Japanese business directories. Capture the company names, their websites, areas of expertise, and any other relevant details.\"\n    },\n    {\n      \"agent\": \"Web\",\n      \"id\": \"2\",\n      \"need\": null,\n      \"task\": \"Perform a similar search to find at least five AI startups in Tokyo. Again, use trusted sources like Crunchbase, TechCrunch, or Japanese business news websites. Gather the same details as for Osaka: company names, websites, areas of focus, and additional information.\"\n    },\n    {\n      \"agent\": \"File\",\n      \"id\": \"3\",\n      \"need\": [\"1\", \"2\"],\n      \"task\": \"Create a new text file named research_japan.txt in the user's home directory. Organize the data collected from both searches into this file, ensuring it is well-structured and formatted for readability. Include headers for Osaka and Tokyo sections, followed by the details of each startup found.\"\n    }\n  ]\n}\n```
        """
        return thought

if __name__ == "__main__":
    provider = Provider("server", "deepseek-r1:14b", "192.168.1.20:3333")
    res = provider.respond(["user", "Hello, how are you?"])
    print("Response:", res)
