#!/bin/bash

# Push to main branch using personal GitHub SSH key
# Use the first remote by default (usually origin)
REMOTE=${1:-$(git remote | head -n 1)}

echo "Pushing to remote '$REMOTE' and branch 'main' using personal SSH key..."
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_rsa_carlosblancosierra" git push $REMOTE main