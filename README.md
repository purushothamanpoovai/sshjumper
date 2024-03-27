## Setup:

  `cd into HOME DIR`

  `git clone git@github.com:purushothamanpoovai/sshjumper.git`

  ### add below into ~/.bash_profile
        
      export PATH="$PATH:$HOME/sshjumper"
      export SSHJCONFIGFILE="$HOME/sshjumper/configs/sshjconfig.yml"     # You must create a sshjconfig.yml and provide the location. See below for instruction
      export SSHJPASSWORDFILE="$HOME/sshjumpergit/sshjumper/configs/passwords.yml"      #To keep passwords and OTP secret. See below for the instruction
      alias :='$HOME/sshjumper/sshjumper'
      source $HOME/sshjumper/bash-completion/ssh-jumper-completion.rc

### sshjconfig.yml
