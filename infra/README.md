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

### 3. Sample Terraform to create ec2

Ref: <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>


``` bash
<!--- set keys --->
export AWS_ACCESS_KEY_ID=
export AWS_SECRET_ACCESS_KEY=

aws configure list
```
```
<!--- main.tf --->
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = ""
}

data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  owners = ["099720109477"] # Canonical
}

resource "aws_instance" "app_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t2.micro"

  tags = {
    Name = "test-terraform"
  }
}
```

``` bash
terraform fmt
```

``` bash
terraform init
terraform validate
```


``` bash
terraform apply
```


