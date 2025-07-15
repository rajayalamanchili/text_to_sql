# Setting development environment codespaces

## Install Terraform and AWS CLI

### 1. Install Terraform CLI

Ref: <https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli>

```bash
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
```

```bash
wget -O- https://apt.releases.hashicorp.com/gpg | \
gpg --dearmor | \
sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null
```

```bash
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/hashicorp.list
```

```bash
sudo apt update
```

```bash
sudo apt-get install terraform
```

### 2. Instal AWS CLI

Ref: <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>

``` bash
<!--- identify os version --->
cat /etc/os-release
```

```bash
curl "<https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip>" -o "awscliv2.zip"
```

```bash
unzip awscliv2.zip
```

```bash
sudo ./aws/install
```

```bash
<!--- Optional: to remove downloaded files --->
rm -f awscliv2.zip
rm -rf aws
```

